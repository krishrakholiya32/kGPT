"""
Email utility for kGPT — sends transactional emails via Resend.
"""
import os

from dotenv import load_dotenv


def send_verification_email(to_email: str, username: str, token: str) -> bool:
    load_dotenv(override=True)
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        print("[kGPT] RESEND_API_KEY not set — skipping verification email")
        return False

    import resend  # imported here so missing package only errors when actually used

    base_url = os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")
    from_email = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    verify_url = f"{base_url}/verify.html?token={token}"

    resend.api_key = api_key

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:40px 24px">
      <h1 style="color:#6c63ff;margin:0 0 4px">kGPT</h1>
      <p style="color:#888;margin:0 0 32px;font-size:13px">Your Private AI Assistant</p>
      <h2 style="color:#111;font-size:20px;margin:0 0 16px">Verify your email address</h2>
      <p style="color:#444;line-height:1.6;margin:0 0 28px">
        Hi <strong>{username}</strong>, click the button below to verify your email
        address and activate your kGPT account.
      </p>
      <a href="{verify_url}"
         style="display:inline-block;padding:13px 28px;background:#6c63ff;color:#fff;
                text-decoration:none;border-radius:8px;font-weight:600;font-size:15px">
        Verify Email &rarr;
      </a>
      <p style="color:#999;font-size:12px;margin:28px 0 4px">Or paste this link in your browser:</p>
      <p style="color:#6c63ff;font-size:12px;word-break:break-all;margin:0">{verify_url}</p>
      <hr style="border:none;border-top:1px solid #eee;margin:32px 0">
      <p style="color:#bbb;font-size:11px;margin:0">
        This link expires in 24 hours. If you did not create a kGPT account, you can ignore this email.
      </p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": f"kGPT <{from_email}>",
            "to": [to_email],
            "subject": "Verify your kGPT email address",
            "html": html,
        })
        return True
    except Exception as exc:
        print(f"[kGPT] Failed to send verification email: {exc}")
        return False
