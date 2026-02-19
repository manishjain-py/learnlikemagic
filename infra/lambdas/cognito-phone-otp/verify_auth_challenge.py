"""
Verify Auth Challenge Response Lambda trigger for Cognito custom auth flow.

Compares the user's submitted answer against the OTP stored in
privateChallengeParameters and returns whether it matches.
"""


def handler(event, context):
    expected = event["request"]["privateChallengeParameters"]["answer"]
    actual = event["request"]["challengeAnswer"]

    event["response"]["answerCorrect"] = expected == actual

    return event
