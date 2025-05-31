# Email Provider Configuration Guide

## Overview

The authentication system now supports multiple email providers as alternatives to SendGrid. The system automatically tries providers in this order of preference:

1. **SendGrid** (Primary)
2. **Resend** (Recommended alternative)
3. **Mailgun** (Popular choice)
4. **SMTP** (Universal fallback)

If no email service is configured, the system will log verification URLs to the console for development purposes.

## Provider Configuration

### 1. SendGrid (Original)

**Pros**: Reliable, comprehensive features, good documentation
**Cons**: Requires verification for production use

**Environment Variables**:
```bash
SENDGRID_API_KEY=your_sendgrid_api_key
EMAIL_FROM=noreply@multivio.com
```

**Setup Steps**:
1. Create account at https://sendgrid.com
2. Generate API key in SendGrid dashboard
3. Verify sender email/domain
4. Add environment variables

### 2. Resend (Recommended Alternative)

**Pros**: Developer-friendly, modern API, easy setup, generous free tier
**Cons**: Newer service, smaller scale than established providers

**Environment Variables**:
```bash
RESEND_API_KEY=your_resend_api_key
EMAIL_FROM=noreply@multivio.com
```

**Setup Steps**:
1. Create account at https://resend.com
2. Generate API key in dashboard
3. Verify domain or use resend.dev for testing
4. Add environment variables

**Installation**:
```bash
pip install resend==3.0.0
```

### 3. Mailgun

**Pros**: Reliable, good deliverability, reasonable pricing
**Cons**: Requires domain verification

**Environment Variables**:
```bash
MAILGUN_API_KEY=your_mailgun_api_key
MAILGUN_DOMAIN=your_verified_domain.com
EMAIL_FROM=noreply@multivio.com
```

**Setup Steps**:
1. Create account at https://mailgun.com
2. Add and verify your domain
3. Get API key from dashboard
4. Add environment variables

**Installation**:
```bash
pip install mailgun==0.1.1
# Note: Uses requests library which is already included
```

### 4. SMTP (Universal Fallback)

**Pros**: Works with any email provider, universal standard
**Cons**: Requires email server configuration

**Environment Variables**:
```bash
SMTP_HOST=smtp.gmail.com  # Example for Gmail
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
EMAIL_FROM=your_email@gmail.com
```

**Popular SMTP Providers**:

**Gmail**:
```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_gmail@gmail.com
SMTP_PASS=your_app_password  # Generate in Google Account settings
```

**Outlook/Hotmail**:
```bash
SMTP_HOST=smtp-mail.outlook.com
SMTP_PORT=587
SMTP_USER=your_email@outlook.com
SMTP_PASS=your_password
```

**Yahoo**:
```bash
SMTP_HOST=smtp.mail.yahoo.com
SMTP_PORT=587
SMTP_USER=your_email@yahoo.com
SMTP_PASS=your_app_password
```

## Quick Setup Guide

### Option 1: Resend (Easiest Alternative)

1. **Sign up**: Go to https://resend.com and create account
2. **Get API Key**: 
   - Dashboard → API Keys → Create API Key
   - Copy the generated key (starts with `re_`)
3. **Configure Environment**:
   ```bash
   RESEND_API_KEY=re_your_api_key_here
   EMAIL_FROM=noreply@multivio.com
   ```
4. **Test**: Use resend.dev domain for testing, or verify your own domain

### Option 2: Gmail SMTP (Free Option)

1. **Enable 2FA**: In Google Account settings
2. **Generate App Password**:
   - Google Account → Security → 2-Step Verification → App Passwords
   - Create password for "Mail"
3. **Configure Environment**:
   ```bash
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your_gmail@gmail.com
   SMTP_PASS=your_16_character_app_password
   EMAIL_FROM=your_gmail@gmail.com
   ```

### Option 3: Mailgun

1. **Sign up**: Go to https://mailgun.com
2. **Verify Domain**: Add your domain and follow DNS verification steps
3. **Get API Key**: Dashboard → API Keys → Private API Key
4. **Configure Environment**:
   ```bash
   MAILGUN_API_KEY=your_mailgun_api_key
   MAILGUN_DOMAIN=your_verified_domain.com
   EMAIL_FROM=noreply@your_verified_domain.com
   ```

## Testing Email Configuration

### Backend Testing

Start FastAPI server and check logs:
```bash
cd /Volumes/ExtremeSSD/workspaces/realworld-workspaces/agdoc
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Look for log messages:
- `Using SendGrid email service`
- `Using Resend email service`
- `Using Mailgun email service`
- `Using SMTP email service`
- `No email service configured. Using fallback logging.`

### Manual Testing

Test email sending via API:
```bash
curl -X POST "http://localhost:8000/api/v1/auth/send-verification-email" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "base_url": "https://dev.multivio.com"
  }'
```

## Environment Variable Priority

The system checks providers in this order and uses the first one with valid configuration:

1. **SendGrid**: `SENDGRID_API_KEY`
2. **Resend**: `RESEND_API_KEY`
3. **Mailgun**: `MAILGUN_API_KEY` + `MAILGUN_DOMAIN`
4. **SMTP**: `SMTP_HOST` + `SMTP_USER` + `SMTP_PASS`

## Troubleshooting

### Common Issues

**1. "No email service configured"**
- Check environment variables are set correctly
- Ensure at least one provider has all required variables

**2. "SendGrid initialization failed"**
- Verify API key is correct and has send permissions
- Check SendGrid account status and limits

**3. "Resend failed to send email"**
- Verify API key format (should start with `re_`)
- Check domain verification status
- Ensure from email matches verified domain

**4. "Mailgun failed to send email"**
- Verify domain is properly verified in Mailgun
- Check API key permissions
- Ensure from email uses verified domain

**5. "SMTP error"**
- Verify SMTP credentials are correct
- Check if 2FA/app passwords are required
- Ensure SMTP port and security settings match provider

### Debug Logging

Enable debug logging to see detailed error messages:
```python
import logging
logging.getLogger('app.utils.email').setLevel(logging.DEBUG)
```

## Production Recommendations

### For High Volume (>10k emails/month)
- **Primary**: SendGrid or Mailgun
- **Backup**: Resend

### For Low-Medium Volume (<10k emails/month)
- **Primary**: Resend
- **Backup**: SMTP (Gmail/Outlook)

### For Development/Testing
- **Option 1**: Resend with resend.dev domain
- **Option 2**: SMTP with personal email
- **Option 3**: Fallback logging (no configuration needed)

## Security Best Practices

1. **Use App Passwords**: For SMTP with Gmail/Outlook
2. **Rotate API Keys**: Regularly update API keys
3. **Environment Variables**: Never commit API keys to code
4. **Domain Verification**: Always verify domains in production
5. **Rate Limiting**: Monitor usage to avoid limits
6. **Backup Provider**: Configure multiple providers for redundancy

## Cost Comparison

| Provider | Free Tier | Paid Plans | Best For |
|----------|-----------|------------|----------|
| **Resend** | 3,000/month | $20/month for 50K | Developers, modern apps |
| **SendGrid** | 100/day | $15/month for 50K | Enterprise, high volume |
| **Mailgun** | 5,000/month | $35/month for 50K | Reliability, deliverability |
| **SMTP** | Varies | Provider dependent | Personal projects, testing |

## Migration Guide

### From SendGrid to Resend
1. Add `RESEND_API_KEY` to environment
2. Remove or comment `SENDGRID_API_KEY`
3. System automatically switches to Resend
4. Test email flow

### Adding Backup Provider
1. Keep primary provider configuration
2. Add secondary provider environment variables
3. System will fallback automatically if primary fails

---

**Implementation Status**: ✅ Complete  
**Last Updated**: January 2025  
**Supports**: SendGrid, Resend, Mailgun, SMTP  
**Fallback**: Console logging for development