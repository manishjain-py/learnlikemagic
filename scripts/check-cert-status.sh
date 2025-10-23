#!/bin/bash
# Check SSL certificate validation status

# Ensure AWS CLI is in PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

CERT_ARN="arn:aws:acm:us-east-1:926211191776:certificate/f4979e52-cb3a-4188-977a-ab46279dfff0"

echo "Checking certificate status..."
echo ""

STATUS=$(aws acm describe-certificate \
  --certificate-arn $CERT_ARN \
  --region us-east-1 \
  --query 'Certificate.Status' \
  --output text)

echo "Status: $STATUS"
echo ""

if [ "$STATUS" = "ISSUED" ]; then
    echo "✅ Certificate is ISSUED and ready to use!"
    echo ""
    echo "Next step: Update CloudFront distribution"
    echo "Run: ./scripts/update-cloudfront-domain.sh"
elif [ "$STATUS" = "PENDING_VALIDATION" ]; then
    echo "⏳ Certificate is pending validation"
    echo ""
    echo "Make sure you added the CNAME record to GoDaddy:"
    echo "  Name: _bd897dc145a6bdb47f94e4fdd7d9f983"
    echo "  Value: _a34b2c410bfd4333b5b62b9125a79799.xlfgrmvvlj.acm-validations.aws."
    echo ""
    echo "DNS propagation can take 5-30 minutes."
    echo "Run this script again to check status."
else
    echo "⚠️  Unexpected status: $STATUS"
fi

echo ""
echo "Certificate ARN: $CERT_ARN"
