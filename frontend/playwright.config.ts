import { defineConfig } from "@playwright/test";

import { resolve } from "node:path";

const key = "local-playwright-demo-key";
const python = resolve(process.env.PLAYWRIGHT_PYTHON ||
  (process.platform === "win32" ? "../.venv/Scripts/python.exe" : "../.venv/bin/python"));

export default defineConfig({
  testDir:"./e2e", workers:1, timeout:45000,
  use:{baseURL:"http://127.0.0.1:3128",channel:process.env.PLAYWRIGHT_CHANNEL||"chrome",
    screenshot:"only-on-failure",trace:"off"},
  webServer:[
    {command:'"'+python+'" e2e/backend.py',url:"http://127.0.0.1:8128/ready",
      env:{PYTHONPATH:"..",LLM_PROVIDER:"mock",DEMO_MODE:"true",EMAIL_MODE:"mock",
        DEMO_DIAGNOSTICS_KEY:key,VERIFICATION_WINDOW_ATTEMPTS:"100"}},
    {command:"npm run start -- --port 3128",url:"http://127.0.0.1:3128",
      env:{BACKEND_API_URL:"http://127.0.0.1:8128",DEMO_DIAGNOSTICS_KEY:key}},
  ],
});
