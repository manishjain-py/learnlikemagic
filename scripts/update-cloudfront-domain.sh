#!/bin/bash
# Update CloudFront distribution with custom domain

set -e

# Ensure AWS CLI is in PATH
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

DISTRIBUTION_ID="E19EYV4ZGTL1L9"
CERT_ARN="arn:aws:acm:us-east-1:926211191776:certificate/f4979e52-cb3a-4188-977a-ab46279dfff0"
DOMAIN="learnlikemagic.com"
WWW_DOMAIN="www.learnlikemagic.com"

echo "========================================="
echo "Updating CloudFront Distribution"
echo "========================================="
echo ""

# Check certificate status first
echo "Checking certificate status..."
STATUS=$(aws acm describe-certificate \
  --certificate-arn $CERT_ARN \
  --region us-east-1 \
  --query 'Certificate.Status' \
  --output text)

if [ "$STATUS" != "ISSUED" ]; then
    echo "❌ Certificate is not issued yet (Status: $STATUS)"
    echo ""
    echo "Please wait for certificate validation to complete."
    echo "Run: ./scripts/check-cert-status.sh"
    exit 1
fi

echo "✅ Certificate is ISSUED"
echo ""

# Get current CloudFront config
echo "Fetching current CloudFront configuration..."
aws cloudfront get-distribution-config \
  --id $DISTRIBUTION_ID \
  --region us-east-1 > /tmp/cf-config.json

# Extract ETag
ETAG=$(cat /tmp/cf-config.json | jq -r '.ETag')
echo "Current ETag: $ETAG"

# Update configuration
echo "Updating configuration..."
cat /tmp/cf-config.json | jq ".DistributionConfig |
  .Aliases.Quantity = 2 |
  .Aliases.Items = [\"$DOMAIN\", \"$WWW_DOMAIN\"] |
  .ViewerCertificate = {
    \"ACMCertificateArn\": \"$CERT_ARN\",
    \"SSLSupportMethod\": \"sni-only\",
    \"MinimumProtocolVersion\": \"TLSv1.2_2021\",
    \"Certificate\": \"$CERT_ARN\",
    \"CertificateSource\": \"acm\"
  }" > /tmp/cf-config-updated.json

# Update CloudFront
echo "Applying changes to CloudFront..."
aws cloudfront update-distribution \
  --id $DISTRIBUTION_ID \
  --distribution-config file:///tmp/cf-config-updated.json \
  --if-match $ETAG \
  --region us-east-1 > /dev/null

echo ""
echo "✅ CloudFront distribution updated!"
echo ""
echo "========================================="
echo "Next Steps"
echo "========================================="
echo ""
echo "1. Wait for CloudFront to deploy (5-10 minutes)"
echo "   Status: aws cloudfront get-distribution --id $DISTRIBUTION_ID --query 'Distribution.Status'"
echo ""
echo "2. Add DNS records in GoDaddy:"
echo ""
echo "   Record 1 (Root domain):"
echo "   Type: CNAME (or ALIAS if supported)"
echo "   Name: @"
echo "   Value: dlayb9nj2goz.cloudfront.net"
echo "   TTL: 600"
echo ""
echo "   Record 2 (WWW subdomain):"
echo "   Type: CNAME"
echo "   Name: www"
echo "   Value: dlayb9nj2goz.cloudfront.net"
echo "   TTL: 600"
echo ""
echo "   ⚠️  Note: GoDaddy doesn't support CNAME for root (@)."
echo "   You may need to use:"
echo "   - A record with CloudFront IP (not recommended - IPs can change)"
echo "   - GoDaddy's forwarding feature"
echo "   - Or just use www.learnlikemagic.com"
echo ""
echo "3. Test after DNS propagation (5-30 minutes):"
echo "   https://learnlikemagic.com"
echo "   https://www.learnlikemagic.com"
echo ""
echo "Distribution ID: $DISTRIBUTION_ID"
echo "Certificate ARN: $CERT_ARN"
