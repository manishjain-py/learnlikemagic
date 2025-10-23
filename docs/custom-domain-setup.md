# Custom Domain Setup Guide

> **Domain:** learnlikemagic.com
> **Registrar:** GoDaddy
> **CDN:** AWS CloudFront
> **Status:** In Progress

## Overview

This guide walks through connecting your custom domain (`learnlikemagic.com`) to your CloudFront distribution.

### What We're Doing

1. **Request SSL Certificate** - Get HTTPS certificate from AWS Certificate Manager
2. **Validate Domain Ownership** - Add DNS records to prove you own the domain
3. **Update CloudFront** - Add custom domain to distribution
4. **Configure DNS** - Point domain to CloudFront

---

## Step 1: Request SSL Certificate ✅ DONE

**Certificate ARN:** `arn:aws:acm:us-east-1:926211191776:certificate/f4979e52-cb3a-4188-977a-ab46279dfff0`

**Domains Covered:**
- `learnlikemagic.com`
- `*.learnlikemagic.com` (wildcard for subdomains)

---

## Step 2: Validate Domain Ownership ✅ DONE

### Add CNAME Record to GoDaddy ✅ DONE

1. **Login to GoDaddy**: https://dcc.godaddy.com/
2. **Select Domain**: learnlikemagic.com
3. **Click**: "DNS" or "Manage DNS"
4. **Click**: "Add" (for new record)

### Record Details ✅ ADDED

| Field | Value |
|-------|-------|
| **Type** | CNAME |
| **Name** | `_bd897dc145a6bdb47f94e4fdd7d9f983` |
| **Value** | `_a34b2c410bfd4333b5b62b9125a79799.xlfgrmvvlj.acm-validations.aws.` |
| **TTL** | 600 (or default) |

**Status**:
- ✅ DNS record added to GoDaddy
- ✅ DNS propagation complete (verified with `dig`)
- ⏳ Awaiting AWS Certificate Manager validation (typically 5-30 minutes)

**Important:**
- GoDaddy may automatically append `.learnlikemagic.com`, so just enter the Name part
- The Value should end with a dot (`.`)
- This single record validates both the root and wildcard domains

### Check Validation Status

Check certificate status:

```bash
./scripts/check-cert-status.sh
```

Or manually:
```bash
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:926211191776:certificate/f4979e52-cb3a-4188-977a-ab46279dfff0 \
  --region us-east-1 \
  --query 'Certificate.Status' \
  --output text
```

Expected output when ready:
```
✅ Certificate is ISSUED and ready to use!
```

**Final Status**:
- ✅ DNS validation record added and propagated
- ✅ AWS Certificate Manager validated the certificate
- ✅ Certificate status: ISSUED

---

## Step 3: Update CloudFront Distribution ✅ DONE

**Script executed successfully!**

Changes applied:
- ✅ Added `learnlikemagic.com` and `www.learnlikemagic.com` as aliases
- ✅ Attached SSL certificate (ARN: ...f4979e52-cb3a-4188-977a-ab46279dfff0)
- ✅ Updated viewer certificate settings (TLSv1.2_2021, SNI-only)

**Final Status**: ✅ CloudFront deployment complete! Status: Deployed

The CloudFront distribution is now configured with:
- Custom domains: `learnlikemagic.com` and `www.learnlikemagic.com`
- SSL certificate attached and active
- Ready to receive traffic

---

## Step 4: Configure DNS Records in GoDaddy (READY TO PROCEED)

After CloudFront deployment completes, add these DNS records:

### Option A: Using www subdomain (Recommended for GoDaddy)

**Record 1 - Root domain forwarding:**
1. In GoDaddy, go to "Forwarding" (not DNS)
2. Add domain forwarding:
   - From: `learnlikemagic.com` (or `@`)
   - To: `https://www.learnlikemagic.com`
   - Forward type: Permanent (301)

**Record 2 - WWW CNAME:**

| Field | Value |
|-------|-------|
| Type | CNAME |
| Name | `www` |
| Value | `dlayb9nj2goz.cloudfront.net` |
| TTL | 600 |

### Option B: Direct root domain (Advanced)

GoDaddy doesn't support CNAME for root (@) domain. Alternatives:

**1. Use ALIAS record (if GoDaddy supports it):**
- Type: ALIAS
- Name: @
- Value: dlayb9nj2goz.cloudfront.net

**2. Use A record with CloudFront IPs (NOT RECOMMENDED - IPs can change)**

**3. Transfer DNS to Route 53 (Recommended for advanced users):**
- Route 53 supports ALIAS records for root domains
- Better integration with AWS services
- See "Transfer to Route 53" section below

---

## Verification

After DNS propagation (5-30 minutes), test:

```bash
# Test HTTPS
curl -I https://learnlikemagic.com
curl -I https://www.learnlikemagic.com

# Both should return 200 OK and show CloudFront headers
```

Or visit in browser:
- https://learnlikemagic.com
- https://www.learnlikemagic.com

Expected:
- ✅ HTTPS (green padlock)
- ✅ Shows your React frontend
- ✅ No certificate warnings

---

## Optional: Transfer DNS to Route 53

For better AWS integration and ALIAS record support:

### 1. Create Hosted Zone

```bash
aws route53 create-hosted-zone \
  --name learnlikemagic.com \
  --caller-reference $(date +%s) \
  --region us-east-1
```

### 2. Note the Name Servers

AWS will provide 4 name servers like:
- ns-1234.awsdns-12.org
- ns-5678.awsdns-34.co.uk
- ns-9012.awsdns-56.com
- ns-3456.awsdns-78.net

### 3. Update Name Servers in GoDaddy

1. Go to GoDaddy domain settings
2. Find "Nameservers" section
3. Change to "Custom"
4. Enter the 4 AWS name servers
5. Save

### 4. Create DNS Records in Route 53

```bash
# Root domain (A record with ALIAS to CloudFront)
aws route53 change-resource-record-sets \
  --hosted-zone-id Z<YOUR-ZONE-ID> \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "learnlikemagic.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "dlayb9nj2goz.cloudfront.net",
          "EvaluateTargetHealth": false
        }
      }
    }]
  }'

# WWW subdomain
aws route53 change-resource-record-sets \
  --hosted-zone-id Z<YOUR-ZONE-ID> \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "www.learnlikemagic.com",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [{"Value": "dlayb9nj2goz.cloudfront.net"}]
      }
    }]
  }'
```

---

## Updating API Domain

After your frontend domain is working, you may want a custom API domain too:

### Option 1: Subdomain (api.learnlikemagic.com)

1. Create CNAME in DNS:
   - Name: `api`
   - Value: `ypwbjbcmbd.us-east-1.awsapprunner.com`

2. Request certificate for `api.learnlikemagic.com`

3. Add custom domain to App Runner (requires App Runner Custom Domain feature)

### Option 2: Use CloudFront for API

Route `/api/*` requests through CloudFront to App Runner backend:
- Requires CloudFront behavior configuration
- Can cache API responses
- Single domain for both frontend and API

---

## Troubleshooting

### Certificate Stuck in "Pending Validation"

**Check:**
1. CNAME record is correct in GoDaddy DNS
2. DNS has propagated:
   ```bash
   dig _bd897dc145a6bdb47f94e4fdd7d9f983.learnlikemagic.com CNAME
   ```
3. Wait longer (can take up to 72 hours, usually 30 minutes)

### "CloudFront does not match domain name"

**Cause:** Certificate not attached to CloudFront

**Solution:** Run `./scripts/update-cloudfront-domain.sh` again

### Site not loading at custom domain

**Check:**
1. DNS records are correct
2. DNS has propagated:
   ```bash
   dig learnlikemagic.com
   dig www.learnlikemagic.com
   ```
3. CloudFront status is "Deployed":
   ```bash
   aws cloudfront get-distribution \
     --id E19EYV4ZGTL1L9 \
     --query 'Distribution.Status'
   ```

### Certificate errors in browser

**Cause:** Using wrong domain or certificate not properly attached

**Check:**
1. You're using HTTPS (not HTTP)
2. Certificate is ISSUED
3. CloudFront has the certificate attached
4. Visiting correct domain (with www if configured that way)

---

## Current Configuration

**CloudFront Distribution:** E19EYV4ZGTL1L9
**CloudFront URL:** dlayb9nj2goz.cloudfront.net
**Certificate ARN:** arn:aws:acm:us-east-1:926211191776:certificate/f4979e52-cb3a-4188-977a-ab46279dfff0
**Custom Domains (after setup):**
- https://learnlikemagic.com
- https://www.learnlikemagic.com

**Backend API:** https://ypwbjbcmbd.us-east-1.awsapprunner.com
**Frontend Environment Variable:** Update `VITE_API_URL` if using custom API domain

---

## Summary Checklist

- [x] SSL certificate requested ✅
- [x] Validation CNAME added to GoDaddy DNS ✅
- [x] Certificate status: ISSUED ✅
- [x] CloudFront distribution updated with domains ✅
- [x] CloudFront deployment complete ✅
- [ ] **→ DNS records added for www subdomain** (NEXT STEP)
- [ ] **→ Root domain configured** (forwarding or ALIAS) (NEXT STEP)
- [ ] Tested: https://learnlikemagic.com
- [ ] Tested: https://www.learnlikemagic.com
- [ ] Updated frontend build if needed
- [ ] Updated documentation ✅

---

## Scripts Reference

```bash
# Check certificate validation status
./scripts/check-cert-status.sh

# Update CloudFront with custom domain (after cert is issued)
./scripts/update-cloudfront-domain.sh

# Check CloudFront deployment status
aws cloudfront get-distribution \
  --id E19EYV4ZGTL1L9 \
  --query 'Distribution.Status'
```

---

**Last Updated:** October 23, 2025
**Status:** WWW subdomain fully working. Root domain needs GoDaddy configuration fix. See `next-steps.txt` for details.

## Quick Status Summary

✅ **Completed Steps:**
1. SSL certificate requested for `learnlikemagic.com` and `*.learnlikemagic.com`
2. DNS validation CNAME record added to GoDaddy
3. Certificate validated and issued by AWS Certificate Manager
4. CloudFront distribution updated with custom domains
5. CloudFront deployment completed successfully

✅ **WWW Subdomain:** https://www.learnlikemagic.com is fully functional and ready for production use!

⚠️ **Root Domain Issue:** learnlikemagic.com returning 405 Not Allowed - needs GoDaddy DNS/forwarding configuration fix

📋 **Next Steps:** See `next-steps.txt` in project root for detailed instructions on fixing root domain

⏰ **Estimated Time:** 5-15 minutes to fix (see next-steps.txt for 3 options)
