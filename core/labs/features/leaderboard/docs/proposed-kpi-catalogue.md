# Lab Mango KPI catalogue

**Proposed specification for member recognition and bench management**
24 November 2026 · Examples use illustrative data.

## Worked example — a five-hour booking

A member reserves Bench A from 09:00 to 14:00, connects at 09:00, finishes at 13:00 and releases the reservation at 13:15. The calendar immediately reopens the remaining time. The whole bench is one bookable resource, available from 09:00 to 17:00, with no other use or reservations that day.

| Perspective | KPI | Result | Calculation |
|---|---|---:|---|
| Member | Booking Attendance | 1 of 1 | Verified use occurred inside the booking. |
| Member | Booking Utilization | 80% | 4 hours used inside the original 5-hour reservation. |
| Member | Slot Adherence | 100% | All 4 connected hours fell inside the reservation. |
| Member and bench | Hours Released | 0.75 h | The 45 minutes from 13:15 to 14:00 became bookable. |
| Bench | Available Hours | 8 h | Scheduled and in service from 09:00 to 17:00. |
| Bench | Booking Occupancy | 53.1% | The booking held 4.25 of 8 available hours. |
| Bench | Remote Utilization | 50% | A remote connection occupied the bench for 4 of 8 available hours. |
| Bench | Unreleased Hours | 0.25 h | The bench remained reserved for 15 minutes after use ended. |

If the member releases the bench immediately at 13:00, Hours Released rises to 1.0 h and Booking Occupancy falls to 50%. Booking Utilization remains 80% because its denominator is the original reservation. A dashboard that shows both measures recognizes prompt release and helps the member choose a future slot length.

## User KPIs

| Dashboard label | Definition and example | Difference from the current KPI |
|---|---|---|
| **Booking Attendance** | Attended bookings divided by eligible, finished bookings with a resolved outcome. Show 18 attended / 20 resolved = 90%, with pending cases alongside. | Current Show-up Rate accepts closed linked sessions wholly outside the slot and can include bookings still in progress. Require verified in-slot use and reconcile missing observations. |
| **Booking Utilization** | Verified in-slot use divided by original reserved duration. Four hours used in a five-hour booking gives 80%. Merge overlapping sessions on the same booking. | Preserve the existing interval union. Show original reserved hours and Hours Released alongside the rate. |
| **Slot Adherence** | Verified linked minutes inside the slot divided by all linked minutes for the booking. A 10:00–15:00 session against a 09:00–14:00 booking gives 4/5 = 80%. | Retain the current calculation. Label the denominator as connected time. |
| **Hours Released** | Eligible unused time made bookable before the original end. Reopening at 13:15 for a 14:00 end returns 0.75 h. | Current Early Release Rate uses completion time and reports a percentage. Lead with recovered hours and retain the percentage in detail. Verify the actual reopening event. |
| **Session Hours** | Cumulative elapsed duration of valid remote connections. Two 90-minute sessions give 3 session-hours. Concurrent connections accumulate separately. | Retire Workday Utilization and its assumed eight-hour workday. Session Hours describe recorded use and carry zero ranking points. |
| **Remote from Home** | Home-origin sessions divided by all remote sessions. Eight verified or declared home sessions out of 20 give 40%. | Replace RFH derived as the complement of the office estimate. Record the source of the classification. |
| **Remote from Office** | Office-origin sessions divided by all remote sessions. Nine verified or declared office sessions out of 20 give 45%. | Replace the RFO estimate based on login frequency. Validate office network classification for on-site and VPN access. |
| **After-Hours Usage** | Session time in 20:00–06:00 lab local time divided by total session time. Three of 12 hours gives 25%. | Retain for staffing and support planning. Remove the evening-use points bonus. |

For the location example, one other known location (5%) and two unknown origins (10%) complete the 20-session total. Historical records without reliable origin evidence remain Unknown.

### Friendly recognition

Publish **Booking Attendance** with attended and eligible counts. Use **Most Improved** for the percentage-point change between comparable periods. Moving from 15/20 to 18/20 earns a 15-point improvement. Award equal recognition for ties. Review monthly booking volumes before setting a minimum sample size. Use comparable booking groups and hold recognition if unresolved cases could change the outcome. This replaces points earned for session frequency, active hours, workday utilization and evening use.

## Bench KPIs

| Dashboard label | Definition and example | Difference from the current KPI |
|---|---|---|
| **Available Hours** | Scheduled bookable hours less verified unavailability within the schedule. Forty scheduled hours less four unavailable hours gives 36 available hours. | Replace 480 minutes per weekday with the effective bench schedule and outage history. Label an assumed baseline Nominal Hours. |
| **Booking Occupancy** | Time held for bookings within available capacity divided by available hours. End each hold when the calendar reopens. In the worked example, 4.25/8 = 53.1%. | Current Booking Occupancy uses original booked time and nominal capacity, giving 5/8 = 62.5% in the example. |
| **Remote Utilization** | Union of remote connection intervals inside available capacity divided by available hours. Two simultaneous connections for one hour on an exclusively bookable bench occupy one bench-hour. | Current Bench Utilization sums active durations, substitutes elapsed time for missing activity and caps the result at 100%. Use the bookable unit consistently. Independently bookable positions require position-hours. |
| **Booking Attendance** | Attended bookings on the bench divided by eligible resolved bookings. Eighteen attended out of 20 gives 90%. Show confirmed no-shows and unresolved cases. | Use finished bookings and verified in-slot evidence. Reconcile local use before assigning a no-show. |
| **Booking Utilization** | Sum of verified in-slot hours divided by sum of original reserved hours. Twelve of 20 reserved hours gives 60%. | Preserve the per-booking interval union. Aggregate underlying hours across bookings. |
| **Hours Released** | Sum of eligible hours actually reopened before scheduled end. Four releases of 45 minutes return 3 h. | Add an absolute capacity measure alongside the existing recovery percentage. Track subsequent rebooking separately. |
| **Unreleased Hours** | Eligible time held after final use and before reopening or slot end. Finishing at 13:00 and reopening at 13:15 leaves 0.25 h unreleased. | Clarify the scope of Idle Reserved Minutes. Retain the current 15-minute minimum eligible tail initially. Report confirmed no-show hours separately. |
| **Users Served** | Distinct identified members with observed use during the period. Twelve members across 40 sessions gives 12 users served. | Refine Active Users using consistent identity resolution and deduplicate across benches for the lab total. |
| **Downtime** | Verified unavailable hours inside the operating schedule. Report 2 h downtime alongside 30/40 scheduled hours monitored. | Replace hardcoded zero and frontend zero defaults with measured values or Unknown. |

## Data quality and release conditions

- **Activity Coverage** reports the share of valid session time for which the agent supplied an activity measurement. Calculate any active-time ratio on that measured subset.
- **Booking Verification** distinguishes verified bookings, sessions without a booking code, and unresolved references. Route unresolved links for review and exclude them from individual penalties.
- Validate the calendar reopening event, effective bench assignments, resource schedules, availability history and session-origin evidence before publishing dependent metrics.
- Show N/A for a zero denominator and Unknown for missing evidence. Publish the reporting period, lab timezone and denominator alongside each rate. Aggregate counts and hours before calculating facility percentages.

## Basis of the proposal

The current-state comparison draws on the Lab Mango backend leaderboard selectors and assessment definitions, session model, and the React leaderboard mapper, table columns, ranking, assessment chart and Excel export. Production telemetry and local operating policies require validation before rollout.
