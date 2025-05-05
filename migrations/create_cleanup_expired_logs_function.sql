-- Create a stored procedure for cleaning up expired logs
CREATE OR REPLACE FUNCTION cleanup_expired_logs()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  DELETE FROM mo_request_log WHERE expires_at < NOW();
END;
$$; 