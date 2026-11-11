# masaladeutsch consistency report

posts audited: **1** · posts with at least one failure: **1**

## Rule summary

| severity | rule | failing | checked |
|---|---|---:|---:|
| BLOCKER | `dark-vars-locked` | 1 | 1 |
| BLOCKER | `js-parses` | 0 | 1 |
| BLOCKER | `no-disclaimer-in-script` | 0 | 1 |
| BLOCKER | `no-inverted-media-query` | 0 | 1 |
| MAJOR | `wpi-attribution` | 0 | 1 |
| MAJOR | `disclaimer-present` | 0 | 1 |
| MINOR | `bw-override` | 1 | 1 |
| MINOR | `translate-widget` | 0 | 1 |
| MINOR | `index-link` | 0 | 1 |
| MINOR | `table-units-in-header` | 0 | 1 |

## Posts needing attention

### screen-process-safety-question-in-five.html
https://masaladeutsch.blogspot.com/2026/11/screen-process-safety-question-in-five.html
- **BLOCKER** `dark-vars-locked` — dark palette consumed with no !important light lock
- **MINOR** `bw-override` — dark palette present with no BW-override / light lock
