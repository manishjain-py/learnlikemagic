"""
Create Auth Challenge Lambda trigger for Cognito custom auth flow.

Generates a random 6-digit OTP, sends it via SNS to the user's phone number,
and stores the OTP in privateChallengeParameters for server-side verification.
"""

import random
import boto3


sns = boto3.client("sns")


def handler(event, context):
    phone = event["request"]["userAttributes"].get("phone_number")
    if not phone:
        raise Exception("User has no phone_number attribute")

    otp = str(random.randint(100000, 999999))

    sns.publish(
        PhoneNumber=phone,
        Message=f"Your LearnLikeMagic verification code is: {otp}",
    )

    event["response"]["publicChallengeParameters"] = {"phone": phone}
    event["response"]["privateChallengeParameters"] = {"answer": otp}
    event["response"]["challengeMetadata"] = f"OTP-{otp}"

    return event
