import open from "open";
import ora from "ora";
import chalk from "chalk";
import { getConfig, saveConfig, getApiUrl } from "../lib/config.js";
import { startDeviceFlow, pollForAuth } from "../lib/auth.js";
import { success, error, info } from "../lib/output.js";

export async function loginCommand(): Promise<void> {
  const existing = getConfig();
  if (existing) {
    info(`Already logged in as ${chalk.bold("@" + existing.github_handle)}.`);
    console.log(
      `Run ${chalk.cyan("secureskillhub logout")} first, or continue to re-authenticate.`,
    );
    // Continue to re-login flow anyway
  }

  const apiUrl = getApiUrl();

  // Step 1: Start device flow
  let flow: Awaited<ReturnType<typeof startDeviceFlow>>;
  try {
    flow = await startDeviceFlow(apiUrl);
  } catch (err) {
    error(
      "Failed to start login flow: " +
        (err instanceof Error ? err.message : String(err)),
    );
    process.exit(1);
  }

  // Step 2: Show user code and open browser
  console.log("");
  console.log(
    `  Open this URL: ${chalk.underline.cyan(flow.verificationUrl)}`,
  );
  console.log(
    `  Enter code:    ${chalk.bold.yellow(flow.userCode)}`,
  );
  console.log("");

  try {
    await open(flow.verificationUrl);
    info("Browser opened automatically.");
  } catch {
    info("Could not open browser — please open the URL manually.");
  }

  // Step 3: Poll for completion
  const spinner = ora("Waiting for authorization...").start();
  const intervalMs = (flow.interval || 5) * 1000;

  try {
    const result = await pollForAuth(apiUrl, flow.deviceCode, intervalMs);
    spinner.stop();
    console.log("");

    // Step 4: Save config
    saveConfig({
      token: result.token,
      github_handle: result.githubHandle,
      api_url: apiUrl,
    });

    success(`Logged in as ${chalk.bold("@" + result.githubHandle)}`);
  } catch (err) {
    spinner.fail("Login failed");
    error(err instanceof Error ? err.message : String(err));
    process.exit(1);
  }
}
