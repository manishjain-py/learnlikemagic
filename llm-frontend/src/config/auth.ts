/**
 * Auth configuration for AWS Cognito.
 * Values come from environment variables set during build.
 */

export const cognitoConfig = {
  UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || '',
  ClientId: import.meta.env.VITE_COGNITO_APP_CLIENT_ID || '',
  Region: import.meta.env.VITE_COGNITO_REGION || 'us-east-1',
  Domain: import.meta.env.VITE_COGNITO_DOMAIN || '',
};

export const googleConfig = {
  ClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID || '',
};
