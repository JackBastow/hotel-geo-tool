# Presence Pro outreach plan (written 2026-11-17)

Built from `Presence_Pro_UK_Hotel_Prospects.xlsx` (104 rows: 57 hotels, 29 groups, 18 agencies). The send schedule, channel, angle and tracking columns are in `outreach_tracker.xlsx` beside this file. This extends `marketing/OUTREACH.md` and keeps its rules.

## The idea in one paragraph
Do not pitch. Give each prospect one true, checkable thing about themselves, offer the free one-page snapshot, and only talk about the Early-joiner offer after they have read it. Ten careful messages a day, never a blast. Agencies come first because one agency yes can reach many hotels.

## Who, in what order
| Segment | Count | Angle | Why |
|---|---|---|---|
| Agencies | 18 | Partner: free snapshot of one client (or a hotel they want to win), then a referral or white-label conversation | One relationship reaches many hotels; they already sell "visibility" and have no AI answer for clients |
| Independent hotels | 57 | Early-joiner offer, led by a snapshot of their own hotel | Owner or GM reads their own email; feel OTA commission most |
| Small and mid groups | 29 (11 held, 8 merged) | Portfolio: dashboard across properties, snapshot of the flagship | Bigger prize (Portfolio tier), slower decision |

Held for later: Hotel du Vin / Malmaison, Red Carnation, Doyle, Exclusive Collection, Hand Picked, Daniel Thwaites, Pig, Splendid, Axiom, Michels & Taylor, Kingfisher (large or procurement-led; OUTREACH.md says skip big chains at the start). Do not contact: PoB Hotels (an association; the listed address is a careers inbox). Merged (one send per inbox): Old Bank and Old Parsonage under Oxford Collection; No.15 under GuestHouse; Dakota Manchester under Dakota Hotels; 11 Cadogan Gardens, Athenaeum and similar rows that share an inbox with their group.

Ordering score: High priority, then a named person, then a marketing inbox, then a general inbox, then a contact form. Agencies get a small bump. That produces 9 waves of about 10 over the next three weeks (Wed 18 Nov onwards, Mon to Thu only).

## Channels
- **Named person or marketing inbox (9 rows):** email from jack@presencepro.co.uk, personal, sent first.
- **General inbox (37 rows):** reservations@, concierge@, info@ and similar. These are guest-facing, so the first line asks them to forward to the GM or marketing lead. Lower hit rate; keep the message very short.
- **Contact form (38 rows):** Chrome drives the form with a 60-word version. Skip any form with a CAPTCHA (never bypass) and do not use a guest booking-enquiry form that cannot be marked as a business message; those go on a LinkedIn list for you to do by hand.
- **LinkedIn:** the sheet has no profile links. For High-priority hotels that do not reply, you send a connection note by hand in week 2.

## Cadence per prospect (maximum two unprompted emails, then stop)
1. **Day 0, message 1:** personal finding plus free snapshot offer.
2. **If they reply "yes":** send the snapshot within one working day, with message 2 two days later (the Early-joiner offer).
3. **Day 7, one nudge only,** and only if there was no reply. Then stop for 90 days.
4. **Any "no" or "unsubscribe":** mark Do not contact in the tracker the same day.

## Making each message personal without making things up
- **Hotels:** the morning of each send, run the Gemini snapshot for that day's ten only (about 40 calls), read the answers, and put one real finding in message 1: named or not, in what position, which rivals appear, or what it said about the hotel. If a snapshot fails or the answer is vague, the hotel is held a day. Never send a finding that was not seen.
- **Agencies:** the personal hook is something checkable on their own site (for example that it already publishes an `llms.txt`), plus the offer of a client snapshot.
- **Groups:** the personal hook is the property count and the flagship snapshot.
- The "Website check" column in the tracker is internal. A missing hotel schema is only a hint (it may be added by script), so it is never quoted in an email.
- Always say it is one assistant on one day. Never promise recommendations or bookings. Never claim customers, results or "limited places" (the offer is the Early-joiner offer).

## Templates
Voice: always the team ("we", signed "The Presence Pro team"). Never a personal name in the body or sign-off, by owner request (2026-11-17).
Sign-off block for every email:

> The Presence Pro team
> presencepro.co.uk
> [postal address once the business has one]
> If you would rather not hear from us, reply "no" and we won't email again.

**Agency, message 1**
> Subject: Free AI-visibility snapshot for one of your hotel clients
>
> Hi {first name},
>
> We run Presence Pro. We check what an AI assistant says when a traveller asks where to stay: whether the hotel is named, who is named instead, and what on the hotel's own site gets in the way.
>
> {personal line, e.g. "We noticed your site already publishes an llms.txt, so you are clearly thinking about how AI reads hotel sites."}
>
> Would a free one-page snapshot for one of your hotel clients be useful, or for a hotel you would like to win? Reply with the hotel's name and we will send it. If it is useful, we would like to talk about how agencies could use the monthly reports with clients.

**Group, message 1**
> Subject: What AI tells guests about {flagship or group}
>
> Hi {first name},
>
> We run Presence Pro. We asked Gemini {question} today, and {finding}. We have put it on one page, with the first things we would fix.
>
> Happy to send it free, and to look at a second property so you can compare across the group. Reply "yes". We are writing to a general address, so if the right person is elsewhere, would you forward this?

**Hotel, message 1** (the finding line is filled from that morning's snapshot)
> Subject: What AI tells guests about {Hotel}
>
> Hi {first name or "there"},
>
> We run Presence Pro. Today We asked Gemini "{question}". {It named {Hotel} {position}, ahead of {rival}. / It did not name {Hotel}; it named {rival 1}, {rival 2} and {rival 3} instead.}
>
> We have put it on one page with the first two or three things we would fix. Free, no catch. Reply "yes" and we will send it. As this is a general address, would you forward it to the GM or whoever looks after your website and marketing?

**Contact form (hotel or agency, 60 words)**
> We run Presence Pro. We checked what an AI assistant says to travellers asking about {Hotel/Agency}: {one finding}. We have a free one-page snapshot. This is a business message, not a booking enquiry: could you pass it to your GM or marketing lead? Reply with "yes" to jack@presencepro.co.uk and we will send it.

**Message 2 (after the snapshot)**
> Hi {name}, did the one-pager make sense? If it is useful, We are taking hotels on an Early-joiner offer at £49.99 a month for the first 12 months (normally £99), in return for feedback on the reports. Details: presencepro.co.uk/founding.html. No pressure either way.

**Day-7 nudge**
> Hi {name}, one last note in case this slipped past: the free snapshot for {Hotel} is still yours if you want it. Just reply "yes". If not, no worries and we will leave you be.

## Reply playbook
| Reply | Action |
|---|---|
| "yes" | Run the full snapshot, send within a working day, log date, schedule message 2 |
| "who are you / how much" | Short honest answer, link to /snapshot.html and /pricing, no discount unless they ask |
| "forward to X" | Thank them, write to X with the same finding, note who referred |
| "not now" | Note a 90-day check-back |
| "no / unsubscribe" | Do not contact, same day |
| Agency interested | Offer a call; discuss referral terms with the owner first (none are set) |

## Open items that block full-scale sending
0. **Sender name:** recipients see the mailbox's display name, which is currently a personal name. Set it to the team name (or send from a team address such as hello@) before anything is sent.
1. **Business details for the footer:** PECR needs a sender identity and a contactable address. No company or address exists yet.
2. **Gemini free quota** ran out today (HTTP 429), so no hotel snapshots exist yet. They run on the day of each send. If the quota stays tight, add a paid key or space the waves out.
3. **Roles are unverified** for the named contacts (Pete Stevens, Tamara de Jong): the sheet says to verify before outreach.
4. **Rothay Manor** is owner-run (possibly a partnership, treated as an individual under PECR): LinkedIn only until the structure is confirmed.
5. **Chrome connector only** works while the Chrome window with the Presence Pro mailbox is open; the employer Outlook connector is deliberately not used.

## Measuring it
Track in the tracker: sent, replied, snapshot sent, Early-joiner started, paid. Review after wave 3 (about 30 sends). If reply rate is under 5%, change the finding line before sending more. Do not widen the list to compensate.
