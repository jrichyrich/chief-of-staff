Schedule recurring monitoring loops from `~/.config/jarvis/startup-loops.txt`.

Read the file and schedule each loop using CronCreate.

## Steps

1. Read `~/.config/jarvis/startup-loops.txt`
2. For each non-blank, non-comment line:
   - Parse the first token as the interval (e.g. `1h`, `30m`, `2h`)
   - The rest of the line is the prompt
   - Convert interval to cron expression:
     - `Nm` where N ≤ 59 → `*/N * * * *`
     - `Nh` where N ≤ 23 → `0 */N * * *`
     - `Nd` → `0 0 */N * *`
   - Avoid the `:00` and `:30` minute marks — pick a random offset (e.g. `7`, `23`, `41`) for each job to stagger API load
   - Call CronCreate with `recurring: true`
3. After all loops are scheduled, output a summary table:

```
| Loop | Interval | Cron | Job ID |
|------|----------|------|--------|
| ... | ... | ... | ... |
```

4. Remind the user: these are session-only (3-day auto-expiry), and they can cancel any with `CronDelete <id>` or view all with `CronList`.

## Important

- Skip lines starting with `#`
- Skip blank lines
- If the file doesn't exist, tell the user and show the expected path
- Use DIFFERENT minute offsets for each job to avoid them all firing at once
- Do NOT ask for confirmation — just schedule them all
