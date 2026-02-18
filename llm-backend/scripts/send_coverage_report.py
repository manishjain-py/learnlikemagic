#!/usr/bin/env python3
"""Send code coverage report via email.

Usage:
    python scripts/send_coverage_report.py \
        --to "manishjain.py@gmail.com" \
        --subject "Code Coverage Report — 2024-01-15" \
        --report "/path/to/report.html" \
        --log "/path/to/logfile.log"

Environment variables required:
    SMTP_HOST     - SMTP server host (default: smtp.gmail.com)
    SMTP_PORT     - SMTP server port (default: 587)
    SMTP_USER     - SMTP username/email
    SMTP_PASSWORD  - SMTP password or app password
"""

import argparse
import os
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def send_email(to: str, subject: str, report_path: str, log_path: str | None = None) -> None:
    """Send coverage report email with attachments."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        print("ERROR: SMTP_USER and SMTP_PASSWORD environment variables are required.", file=sys.stderr)
        print("Set these in your environment or .env file:", file=sys.stderr)
        print("  export SMTP_USER='your-email@gmail.com'", file=sys.stderr)
        print("  export SMTP_PASSWORD='your-app-password'", file=sys.stderr)
        sys.exit(1)

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to
    msg["Subject"] = subject

    body = "See attached HTML coverage report and log file for details."
    msg.attach(MIMEText(body, "plain"))

    # Attach report
    report_file = Path(report_path)
    if report_file.exists():
        with open(report_file, "rb") as f:
            attachment = MIMEApplication(f.read(), Name=report_file.name)
            attachment["Content-Disposition"] = f'attachment; filename="{report_file.name}"'
            msg.attach(attachment)
    else:
        print(f"WARNING: Report file not found: {report_path}", file=sys.stderr)

    # Attach log file if provided
    if log_path:
        log_file = Path(log_path)
        if log_file.exists():
            with open(log_file, "rb") as f:
                attachment = MIMEApplication(f.read(), Name=log_file.name)
                attachment["Content-Disposition"] = f'attachment; filename="{log_file.name}"'
                msg.attach(attachment)
        else:
            print(f"WARNING: Log file not found: {log_path}", file=sys.stderr)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to], msg.as_string())
        print(f"Email sent successfully to {to}")
    except smtplib.SMTPAuthenticationError:
        print("ERROR: SMTP authentication failed. Check SMTP_USER and SMTP_PASSWORD.", file=sys.stderr)
        sys.exit(1)
    except smtplib.SMTPException as e:
        print(f"ERROR: Failed to send email: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Send code coverage report via email")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument("--report", required=True, help="Path to HTML report file")
    parser.add_argument("--log", default=None, help="Path to log file (optional)")

    args = parser.parse_args()
    send_email(args.to, args.subject, args.report, args.log)


if __name__ == "__main__":
    main()
