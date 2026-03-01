import { ApiClient } from "./api-client.js";
import type { DeviceFlowStart, DeviceFlowPollResult } from "./types.js";

/**
 * Initiate the GitHub OAuth device flow via our API.
 */
export async function startDeviceFlow(
  apiUrl: string,
): Promise<{
  deviceCode: string;
  userCode: string;
  verificationUrl: string;
  expiresIn: number;
  interval: number;
}> {
  const client = new ApiClient(apiUrl);
  const result = await client.post<DeviceFlowStart>("/v1/auth/device");
  return {
    deviceCode: result.device_code,
    userCode: result.user_code,
    verificationUrl: result.verification_url,
    expiresIn: result.expires_in,
    interval: result.interval,
  };
}

/**
 * Poll the API for device flow completion.
 * Resolves when the user completes auth or the flow expires.
 */
export async function pollForAuth(
  apiUrl: string,
  deviceCode: string,
  intervalMs: number = 5000,
): Promise<{
  token: string;
  githubHandle: string;
}> {
  const client = new ApiClient(apiUrl);
  const maxAttempts = Math.ceil((15 * 60 * 1000) / intervalMs); // 15 minutes

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const result = await client.post<DeviceFlowPollResult>(
      "/v1/auth/device/poll",
      { device_code: deviceCode },
    );

    if (result.status === "complete" && result.token && result.github_handle) {
      return {
        token: result.token,
        githubHandle: result.github_handle,
      };
    }

    if (result.status === "expired") {
      throw new Error("Device flow expired. Please try logging in again.");
    }

    // Wait before next poll
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }

  throw new Error("Login timed out after 15 minutes. Please try again.");
}
