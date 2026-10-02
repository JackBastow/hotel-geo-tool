"""Offline tests for profile discovery and URL tidying. Run: python test_discovery.py"""
import full_audit

fails = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        fails.append(name)


t = full_audit._tidy_profile_url
print("1. the real bad URL from a live site")
check("HTML entity and TikTok tracking removed",
      t("TikTok", "https://www.tiktok.com/@brooklandshotel?_r=1&#038;_t=ZN-94DjKx4BLVb")
      == "https://www.tiktok.com/@brooklandshotel")
check("Instagram igsh tracking removed",
      t("Instagram", "https://www.instagram.com/brooklands_hotel/?igsh=abc123")
      == "https://www.instagram.com/brooklands_hotel")
check("Facebook fbclid removed",
      t("Facebook", "https://www.facebook.com/BHSurrey/?fbclid=xyz")
      == "https://www.facebook.com/BHSurrey")
check("a clean URL is unchanged apart from the trailing slash",
      t("Facebook", "https://www.facebook.com/BHSurrey/") == "https://www.facebook.com/BHSurrey")

print("2. links where the query IS the content are left alone")
gm = "https://www.google.com/maps/dir//Brooklands+Hotel/@51.35,-0.47,15z?entry=ttu"
check("Google Maps links keep their query", t("Google Maps", gm) == gm)
check("entities are still decoded for them", "&" in t("Google Maps", "https://x.com/?a=1&amp;b=2")
      and "&amp;" not in t("Google Maps", "https://x.com/?a=1&amp;b=2"))

print("3. discovery on real-looking HTML")
html = ('<a href="https://www.tiktok.com/@h?_r=1&#038;_t=Z">t</a>'
        '<a href="https://www.instagram.com/p/ABC123/">a post</a>'
        '<a href="https://www.youtube.com/watch?v=abc">a video</a>'
        '<a href="https://www.facebook.com/H/">fb</a>')
d = full_audit.discover_profiles("https://h.com/", prefetched=[html])
found = {p["platform"]: p["url"] for p in d["profiles"]}
check("TikTok profile is clean", found.get("TikTok") == "https://www.tiktok.com/@h", found)
check("an individual Instagram post is not mistaken for the profile", "Instagram" not in found)
check("a YouTube watch link is not mistaken for a channel", "YouTube" not in found, found)
check("Facebook found", found.get("Facebook") == "https://www.facebook.com/H")

print()
print("FAILURES:", fails if fails else "none")
raise SystemExit(1 if fails else 0)
