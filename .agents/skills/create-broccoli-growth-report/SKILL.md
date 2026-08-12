---
name: create-broccoli-growth-report
description: Validate broccoli camera images, measured smart-farm sensor data, and system logs, then create trustworthy daily, weekly, or monthly growth reports and concise Telegram summaries. Use for broccoli growth observation reports, camera-based crop assessments, EC/pH/environment evaluations, report PDFs, and automated report workflows where data provenance, quantitative computer-vision limits, confidence, and human verification must be explicit.
---

# Create Broccoli Growth Report

Create an auditable report. Never turn an AI impression into a measured value.

## Workflow

1. Read `references/report-spec.md`.
2. Label every input as `실측`, `계산`, `AI 관찰`, `가상`, or `미입력`.
3. Validate the camera ID, capture time, server receipt time, resolution, viewpoint, and image usability. Treat each timestamp as a different field unless its meaning is documented.
4. Record each sensor's model/ID, interval, sample count, time range, average, minimum, maximum, unit, accepted range, and calibration date. Never relabel virtual data as measured.
5. Describe only visible leaf spread, color change, wilting, damage, and spatial differences. Use `정상`, `주의`, `경고`, or `판단 불가`, and provide a reason for confidence.
6. Report canopy coverage, greenness, or uniformity as a number only when a deterministic image pipeline produced it with a valid ROI, controlled/calibrated lighting, method version, quality check, and saved evidence overlay. Otherwise output `산출 불가` with the missing requirement.
7. Keep report recommendations separate from actuator control. Never issue pump, relay, fan, LED, EC, or pH commands from this workflow.
8. Create the PDF by running:

   ```powershell
   py .agents\skills\create-broccoli-growth-report\scripts\generate_daily_report.py `
     --input <daily-report.json> `
     --photo <camera-photo.jpg> `
     --output <report.pdf>
   ```

9. Use optional `--reporter-signature` and `--reviewer-stamp` only when `review.approved` is `true` and the named people approved that exact report.
10. Render every PDF page and visually verify it before delivery. Produce a Telegram summary only from the same verified report data.

## Production Gate

Do not call the system validated until all conditions are met:

- Fixed camera geometry and repeatable lighting exist.
- Sensor timestamps, source IDs, and calibration history are stored.
- At least 30-100 representative images have human ground truth.
- Calculated metrics have documented error against manual labels.
- Unsuitable frames return `산출 불가` instead of a fabricated value.
- AI and human conclusions are stored separately.

## Completion Checks

- Tag every number as measured, calculated, or virtual.
- Attach a source and time range to every measured value.
- Attach method/version and evidence to every calculated visual metric.
- Keep unknown DAT and unavailable views explicitly unknown.
- Include the limitations statement and human review state.
- Never imply a signature, seal, or approval without authorization.
