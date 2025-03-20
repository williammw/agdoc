-- Clear all OAuth states
DELETE FROM mo_oauth_states WHERE platform = 'linkedin';

-- Clear all LinkedIn social accounts (optional - only if you want to completely start over)
DELETE FROM mo_social_accounts WHERE platform = 'linkedin';
