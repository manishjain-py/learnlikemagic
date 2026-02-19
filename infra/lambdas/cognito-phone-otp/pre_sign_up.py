"""
Pre Sign-Up Lambda trigger for Cognito.

Auto-confirms users who sign up with a phone number so they can
immediately proceed to the custom auth (OTP) flow without needing
manual confirmation or email verification.
"""


def handler(event, context):
    # Auto-confirm phone-based signups
    if event["request"].get("userAttributes", {}).get("phone_number"):
        event["response"]["autoConfirmUser"] = True
        event["response"]["autoVerifyPhone"] = True

    return event
