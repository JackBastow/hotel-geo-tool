"""Entry point for the web host: `waitress-serve --port=$PORT wsgi:app` (see render.yaml)."""

from server import create_app

app = create_app()

if __name__ == "__main__":
    import os

    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), threads=8)
