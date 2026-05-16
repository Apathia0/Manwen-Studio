import { spawn } from "node:child_process";
import { dirname, delimiter } from "node:path";
import ffmpegPath from "ffmpeg-static";
import ffprobePkg from "ffprobe-static";

const ffprobePath = ffprobePkg.path;
const tool = process.argv[2];
const extraArgs = process.argv.slice(3);

if (!tool) {
  console.error("Usage: node scripts/run-hyperframes.mjs <command> [...args]");
  process.exit(1);
}

const env = {
  ...process.env,
  PATH: [dirname(ffmpegPath), dirname(ffprobePath), process.env.PATH || ""].join(delimiter),
};

const child = spawn(
  "npx",
  ["--yes", "hyperframes@0.6.2", tool, ...extraArgs],
  {
    stdio: "inherit",
    shell: true,
    env,
  },
);

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
