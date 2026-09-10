import { test, expect } from "@playwright/test";
import { mkdir, writeFile, unlink } from "node:fs/promises";
import path from "node:path";
test("MCP demo executes, persists and exposes actual diff and verifier evidence", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Run MCP demo", exact: true }).click();
  await expect(page.locator(".detail .status").first()).toHaveText(
    "succeeded",
    { timeout: 30000 },
  );
  await expect(page.locator(".timeline")).toContainText("mcp");
  const id = await page.locator(".detail h2").first().textContent();
  await page.getByRole("tab", { name: "Diff", exact: true }).click();
  await expect(page.locator(".diff")).toContainText("min(high, value)");
  await page.screenshot({ path: "../docs/assets/diff.png", fullPage: false });
  await page.getByRole("tab", { name: "Verification", exact: true }).click();
  await expect(
    page.getByText("Executable checks passed", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/assets/verification.png",
    fullPage: false,
  });
  await page.getByRole("tab", { name: "Context", exact: true }).click();
  await expect(page.locator(".context-summary")).toContainText("tokens");
  await page.reload();
  await page.getByRole("button").filter({ hasText: id! }).first().click();
  await expect(page.locator(".detail .status").first()).toHaveText("succeeded");
  await page.getByRole("button", { name: "Retry task" }).click();
  await expect(page.locator(".detail h2").first()).not.toHaveText(id!);
  await expect(page.locator(".detail .status").first()).toHaveText(
    "succeeded",
    { timeout: 30000 },
  );
  expect(await page.locator(".detail h2").first().textContent()).not.toBe(id);
  expect(errors).toEqual([]);
});
test("evaluation distinguishes contract controls from unrun model experiments", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Evaluation", exact: true }).click();
  await expect(page.getByText("36 / 36", { exact: true })).toBeVisible();
  await expect(
    page.getByText("not run", { exact: true }).first(),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/assets/evaluation.png",
    fullPage: false,
  });
  await page.getByText("Inspect all 36 independent task contracts").click();
  await expect(
    page.getByText("arc-036-document-boss-contract", { exact: true }),
  ).toBeVisible();
});
test("memory can be invalidated and overview reports provider counts", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Memory", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Invalidate memory" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "Invalidate memory" }).first().click();
  await expect(
    page.getByRole("button", { name: "Invalidated", exact: true }).first(),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(
    page.getByText("Deterministic fixture", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/assets/overview.png",
    fullPage: false,
  });
});
test("unconfigured DeepSeek blocks browser submission and the API fails closed", async ({
  page,
  request,
}) => {
  const health = await (await request.get("/api/health")).json();
  test.skip(
    health.real_provider_configured,
    "This check requires an intentionally unconfigured provider",
  );
  await page.goto("/");
  await page.getByLabel("Git repository path").fill(health.demo_repository);
  await page.getByLabel("What should change?").fill("Fix clamp boundary bug");
  await page.getByLabel("Model provider").selectOption("openai");
  await expect(
    page.getByRole("button", { name: "Run task", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("DeepSeek is not configured.", { exact: true }),
  ).toBeVisible();
  const attempt = await request.post("/api/tasks", {
    data: {
      repository: health.demo_repository,
      task: "Fix clamp boundary bug",
      provider: "openai",
    },
  });
  expect(attempt.status()).toBe(202);
  const queued = await attempt.json();
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/tasks/" + queued.task_id)).json())
          .status,
    )
    .toBe("failed");
  const failed = await (
    await request.get("/api/tasks/" + queued.task_id)
  ).json();
  expect(failed.error).toContain("OPENAI_API_KEY");
});
test("DeepSeek selection submits the remote provider with explicit bounded budgets and no browser key", async ({
  page,
  request,
}, testInfo) => {
  const health = await (await request.get("/api/health")).json();
  const submitted: Record<string, unknown>[] = [];
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: {
        ...health,
        real_provider_configured: true,
        real_provider: {
          configured: true,
          flavor: "deepseek",
          model: "deepseek-flash",
        },
      },
    }),
  );
  await page.route("**/api/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    submitted.push(route.request().postDataJSON());
    await route.fulfill({
      status: 422,
      json: { detail: "Contract intercepted: no provider call executed." },
    });
  });
  await page.goto("/");
  await page.getByLabel("Git repository path").fill(health.demo_repository);
  await page
    .getByLabel("What should change?")
    .fill("Fix the authored clamp fixture");
  await page.getByLabel("Model provider").selectOption("openai");
  await expect(
    page.getByText("DeepSeek configured · deepseek-flash", { exact: true }),
  ).toBeVisible();
  expect(submitted).toHaveLength(0);
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await page
    .getByText("Budget and executable acceptance criteria", { exact: true })
    .click();
  await expect(page.getByLabel("Maximum steps", { exact: true })).toHaveValue(
    "6",
  );
  await expect(
    page.getByLabel("Total token budget", { exact: true }),
  ).toHaveValue("16000");
  await page.getByLabel("Maximum steps", { exact: true }).fill("4");
  await page.getByLabel("Total token budget", { exact: true }).fill("12000");
  await page
    .getByLabel("I trust this repository’s test code to run locally")
    .check();
  await page.screenshot({
    path: testInfo.outputPath("deepseek-ui-contract.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "Run task", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Contract intercepted: no provider call executed.",
  );
  expect(submitted).toHaveLength(1);
  expect(submitted[0]).toMatchObject({
    provider: "openai",
    allow_repository_code: true,
    budget: {
      max_steps: 4,
      max_tokens: 12000,
      timeout_seconds: 180,
      max_repairs: 0,
      context_tokens: 1800,
      provider_retries: 0,
    },
  });
  expect(JSON.stringify(submitted[0])).not.toMatch(
    /api[_-]?key|authorization|bearer/i,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
});
test("mobile layout remains operable without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Run MCP demo", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "../docs/assets/mobile.png", fullPage: true });
});
test("destructive replay pauses for approval, permits rejection, and can be cancelled", async ({
  page,
  request,
}) => {
  const health = await (await request.get("/api/health")).json();
  const id = "ui-approval-" + Date.now();
  const dir = path.resolve("..", ".repopilot", "recordings");
  await mkdir(dir, { recursive: true });
  const recording = path.join(dir, id + ".json");
  await writeFile(
    recording,
    JSON.stringify([
      {
        action: {
          kind: "tool",
          summary: "Delete only the isolated demo README",
          tool: "apply_patch",
          arguments: { path: "README.md", delete: true },
        },
      },
      { action: { kind: "finish", summary: "Deletion complete" } },
    ]),
  );
  try {
    for (const action of [
      "Reject deletion",
      "Approve deletion",
      "Cancel task",
    ]) {
      const created = await (
        await request.post("/api/tasks", {
          data: {
            repository: health.demo_repository,
            task: "Remove fixture README after explicit approval",
            provider: "replay",
            replay_id: id,
            skill: null,
            use_verifier: false,
          },
        })
      ).json();
      await page.goto("/");
      await page
        .getByRole("button")
        .filter({ hasText: created.task_id.slice(0, 12) })
        .first()
        .click();
      await expect(
        page.getByText("Deletion needs your review", { exact: true }),
      ).toBeVisible();
      if (action === "Reject deletion")
        await page.screenshot({
          path: "../docs/assets/approval.png",
          fullPage: false,
        });
      await page.getByRole("button", { name: action, exact: true }).click();
      await expect(page.locator(".detail .status").first()).toHaveText(
        action === "Reject deletion"
          ? "failed"
          : action === "Approve deletion"
            ? "unverified"
            : "cancelled",
      );
    }
  } finally {
    await unlink(recording);
  }
});
