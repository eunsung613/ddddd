# Broccoli Report Specification

## Required input contract

| Group | Required fields |
|---|---|
| Report | date, crop, facility, zone, DAT or `미입력` |
| Image | camera ID, capture time, server receipt time, resolution, viewpoint |
| Sensor series | source type, sensor ID, unit, start/end, count, mean, minimum, maximum, calibration date |
| System | camera clock state, missing-data periods, communication errors |
| Analysis | actual model ID, prompt version, generation time, code/formula version |
| Review | AI result, human result, reviewer, review time, approval state |

Never silently fill a missing value. Mark it `미입력`, `확인 필요`, or `판단 불가`.

## Quantitative image metrics

### Canopy coverage

- Formula: `valid plant pixels / valid cultivation ROI pixels * 100`.
- Require a saved ROI, segmentation method/version, and overlay.
- Exclude aisles, pipes, reflections, and borders from the denominator.

### Greenness

- Use a versioned HSV or calibrated color formula on segmented leaf pixels.
- Record white balance, exposure conditions, and formula.
- Interpret primarily as a within-camera time-series trend until color calibration is validated.

### Uniformity

- Use fixed plant-position ROIs or validated instance segmentation.
- Record per-plant values and the variation formula.
- Do not calculate when overlapping plants cannot be separated reliably.

## Status

- `정상`: supplied evidence is within documented criteria.
- `주의`: deviation or uncertainty requires a scheduled check.
- `경고`: a documented threshold breach or critical failure requires prompt action.
- `판단 불가`: required evidence is missing or unsuitable.

Confidence must include its reason. Confidence does not replace missing evidence.

Use this statement in every final report:

> 본 보고서는 영상 및 센서 데이터에 기반한 생육 의사결정 지원 자료이며, 병해충과 생리장해의 확정 진단을 대체하지 않는다.

## Telegram summary

Include only:

1. Date and overall status
2. EC, pH, air temperature, and humidity with source labels
3. Image observation and confidence
4. Warnings or `산출 불가` items
5. Required field checks
6. Link or attachment for the full report
