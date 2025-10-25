# Content Management API Setup

This document explains the content management API implementation for the Multivio social media management platform.

## ✅ What's Implemented

### Database Tables
- **post_groups**: Container for organizing multiple related posts
- **post_drafts**: Individual posts (uses existing table structure)

### API Endpoints
All endpoints are available at `${API_URL}/api/v1/content/`

#### Post Groups
- `GET /groups` - Get all post groups for user
- `POST /groups` - Create new post group
- `PUT /groups/{id}` - Update post group
- `DELETE /groups/{id}` - Delete post group

#### Post Drafts
- `GET /drafts` - Get all drafts for user
- `POST /drafts` - Save new draft
- `PUT /drafts/{id}` - Update existing draft
- `DELETE /drafts/{id}` - Delete draft

#### Publishing
- `POST /publish` - Publish posts (immediate or scheduled)
- `POST /schedule` - Schedule posts for later

### Frontend Integration
- **Save Draft**: Saves current post group content to database
- **Publish Now**: Saves draft and publishes immediately
- **Schedule Posts**: Saves draft and schedules for later publishing

## 🚀 Setup Instructions

### 1. Database Migration
The content management tables have been created in your Supabase database:
- `post_groups` table for organizing posts
- Updated `post_drafts` table structure

### 2. Backend Deployment
The FastAPI backend at `https://dev.ohmeowkase.com` includes the new content endpoints.

### 3. Frontend Integration
The Content Creation V2 page now connects to the API:
- Publish button calls `/api/v1/content/publish`
- Save Draft button calls `/api/v1/content/drafts`
- Schedule functionality integrated

## 🧪 Testing the Implementation

### Test Save Draft
1. Go to https://dev.multivio.com/dashboard/content
2. Create a new post group
3. Add platforms and content
4. Click "Save Draft"
5. Check browser network tab for API call to `/content/drafts`

### Test Publish
1. After creating content, click "Publish Now"
2. Should see success message if draft saves and publishes
3. Check browser network tab for API calls

### Test Schedule
1. Set a schedule date and time
2. Click "Publish Now" (will schedule instead)
3. Should see scheduled confirmation

## 📊 API Response Format

### Success Response
```json
{
  "success": true,
  "data": {...},
  "message": "Operation completed successfully"
}
```

### Error Response
```json
{
  "success": false,
  "message": "Error description",
  "errors": ["Detailed error messages"]
}
```

## 🔧 Current Limitations

### Mock Publishing
- Publishing is currently mocked (updates status to "published")
- Real platform integration would require:
  - Platform-specific API calls (Twitter API, Facebook Graph API, etc.)
  - OAuth token management
  - Error handling for platform limits

### Media Handling
- Media upload and storage not yet implemented
- Currently stores media metadata only
- Would need cloud storage integration (AWS S3, etc.)

### Scheduling
- Schedule functionality sets status but doesn't execute
- Would need background job processor (Celery, etc.)

## 🎯 Next Steps for Full Implementation

1. **Real Platform Publishing**
   - Integrate Twitter API v2
   - Facebook Graph API integration
   - LinkedIn API integration
   - YouTube Data API

2. **Media Storage**
   - Implement file upload endpoints
   - Cloud storage integration
   - Image/video processing

3. **Background Jobs**
   - Scheduled post execution
   - Retry mechanisms
   - Status notifications

4. **Enhanced Features**
   - Draft versioning
   - Collaboration features
   - Analytics integration

## 🐛 Troubleshooting

### API Not Responding
- Check if backend is running at `https://dev.ohmeowkase.com`
- Verify authentication token is valid
- Check browser network tab for error details

### Database Errors
- Ensure Supabase connection is working
- Check if migration was applied successfully
- Verify user has proper permissions

### Frontend Errors
- Check browser console for JavaScript errors
- Verify API URL environment variable
- Test authentication flow

## 📞 Testing Commands

You can test the API directly:

```bash
# Get authentication token (replace with your Firebase token)
TOKEN="your_firebase_token_here"

# Test create draft
curl -X POST "https://dev.ohmeowkase.com/api/v1/content/drafts" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "Test Post",
    "content_mode": "universal",
    "universal_content": "Hello World!",
    "selected_platforms": [{"provider": "twitter", "displayName": "My Twitter"}]
  }'

# Test publish
curl -X POST "https://dev.ohmeowkase.com/api/v1/content/publish" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "Test Post",
    "immediate": true
  }'
```

This implementation provides a solid foundation for the content management system with room for future enhancements!