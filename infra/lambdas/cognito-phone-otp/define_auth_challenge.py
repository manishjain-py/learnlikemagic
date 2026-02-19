"""
Define Auth Challenge Lambda trigger for Cognito custom auth flow.

Decides what happens next in the authentication flow based on session history:
- No previous challenge → issue a CUSTOM_CHALLENGE (send OTP)
- Previous challenge answered correctly → mark authenticated
- 3+ failed attempts → mark failed (brute force protection)
"""


def handler(event, context):
    session = event["request"]["session"]

    if not session:
        # First attempt: issue a custom challenge
        event["response"]["issueTokens"] = False
        event["response"]["failAuthentication"] = False
        event["response"]["challengeName"] = "CUSTOM_CHALLENGE"
    elif len(session) >= 3 and not session[-1].get("challengeResult"):
        # 3+ attempts and last one failed: block authentication
        event["response"]["issueTokens"] = False
        event["response"]["failAuthentication"] = True
    elif session[-1].get("challengeResult"):
        # Last challenge was answered correctly: issue tokens
        event["response"]["issueTokens"] = True
        event["response"]["failAuthentication"] = False
    else:
        # Challenge not yet answered correctly: issue another challenge
        event["response"]["issueTokens"] = False
        event["response"]["failAuthentication"] = False
        event["response"]["challengeName"] = "CUSTOM_CHALLENGE"

    return event
