import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
from collections import defaultdict

st.set_page_config(page_title="Attendance Analyzer", layout="wide")

def parse_excel(file, month):
    workbook = pd.read_excel(file, sheet_name="Attendance Logs", header=None)
    rows = []

    for idx, row in workbook.iterrows():
        if str(row[9]).strip() == "Name":
            name = str(workbook.iloc[idx][11]).strip()
            nums = workbook.iloc[idx + 1]
            days = workbook.iloc[idx + 2]
            times = workbook.iloc[idx + 3]

            # Optional: Debug prints to check columns
            print(f"Days row values: {nums.tolist()}")
            print(f"Weekdays row values: {days.tolist()}")

            # Dynamically find the first day column
            first_day_col = None
            for col in range(len(workbook.columns)):
                day_str = str(nums[col]).strip()
                if day_str.isdigit() and (1 <= int(day_str) <= 31):
                    first_day_col = col
                    break

            if first_day_col is None:
                raise ValueError("Couldn't find the starting day column in the sheet.")

            # Process from the first detected day column onward
            for col in range(first_day_col, len(workbook.columns)):
                weekday = str(days[col]).strip()
                day_str = str(nums[col]).strip()
                raw_times = str(times[col]).strip()

                if not re.match(r"Sun|Mon|Tue|Wed|Thu|Fri|Sat", weekday):
                    continue
                if not day_str.isdigit():
                    continue
                if not raw_times or raw_times.lower() == "nan":
                    continue

                try:
                    day_int = int(day_str)
                    if not (1 <= day_int <= 31):
                        continue

                    time_list = re.findall(r"\d{1,2}:\d{2}", raw_times)
                    rows.append({
                        "EmployeeName": name,
                        "Date": datetime(2025, month, day_int),
                        "Times": time_list,
                        "OriginalRawTime": raw_times
                    })
                except ValueError:
                    continue

    # Sort records by date to ensure chronological processing
    rows.sort(key=lambda x: x['Date'])
    return rows

def filter_zero_hour_employees(summaries):
    """
    Removes employees with total worked hours equal to 0.
    """
    return [summary for summary in summaries if summary["TotalHours"] > 0]

def analyze_attendance(records):
    from collections import defaultdict

    grouped = defaultdict(list)
    for r in records:
        grouped[r['EmployeeName']].append(r)

    result = []

    for name, logs in grouped.items():
        logs.sort(key=lambda x: x['Date'])
        total_hours = 0
        missing = []
        daily_details = []

        # ---- Handle first day early checkout ----
        if logs:
            first_log = logs[0]
            first_times = first_log['Times']
            if first_times:
                first_time_obj = datetime.strptime(first_times[0], "%H:%M").time()
                if first_time_obj.hour < 4 or (first_time_obj.hour == 4 and first_time_obj.minute <= 30):
                    note_msg = (
                        f"{first_log['Date'].strftime('%Y-%m-%d')} checkout at {first_times[0]} is likely "
                        f"for previous day not included in this file."
                    )
                    missing.append(note_msg)
                    first_log['Times'] = first_log['Times'][1:]  # Remove the early checkout time

        i = 0
        while i < len(logs):
            current = logs[i]
            times = current['Times']
            handled = False

            print(f"Processing {name} - {current['Date'].strftime('%Y-%m-%d')} - Times: {times}")

            processed_indices = set()

            if len(times) >= 2:
                pair_limit = len(times) if len(times) % 2 == 0 else len(times) - 1

                for t in range(0, pair_limit, 2):
                    try:
                        start = datetime.combine(current['Date'], datetime.strptime(times[t], "%H:%M").time())
                        end = datetime.combine(current['Date'], datetime.strptime(times[t + 1], "%H:%M").time())
                        if end < start:
                            end += timedelta(days=1)
                        duration = (end - start).total_seconds() / 3600
                        total_hours += duration

                        daily_details.append({
                            "Date": current['Date'].strftime("%Y-%m-%d"),
                            "Start": times[t],
                            "End": times[t + 1],
                            "Duration": round(duration, 2)
                        })

                        processed_indices.update([t, t+1])  # Mark processed
                    except Exception as e:
                        print(f"Pairing error on {current['Date']} for times {times[t]}-{times[t+1]}: {e}")

                handled = True

            # After processing pairs, check if there's an unpaired leftover check-in
            unprocessed_times = [
                (idx, times[idx]) for idx in range(len(times)) if idx not in processed_indices
            ]

            if len(unprocessed_times) == 1:
                idx, leftover_time = unprocessed_times[0]

                # Try pairing with next day's early check-in if it exists
                if i + 1 < len(logs):
                    next_log = logs[i + 1]
                    next_times = next_log['Times']
                    if next_times:
                        next_first_time_obj = datetime.strptime(next_times[0], "%H:%M").time()
                        if next_first_time_obj.hour < 4 or (next_first_time_obj.hour == 4 and next_first_time_obj.minute <= 30):
                            start_dt = datetime.combine(current['Date'], datetime.strptime(leftover_time, "%H:%M").time())
                            next_first_dt = datetime.combine(next_log['Date'], next_first_time_obj)
                            if next_first_dt <= start_dt:
                                next_first_dt += timedelta(days=1)

                            duration = (next_first_dt - start_dt).total_seconds() / 3600
                            total_hours += duration
                            daily_details.append({
                                "Date": current['Date'].strftime("%Y-%m-%d"),
                                "Start": leftover_time,
                                "End": next_times[0],
                                "Duration": round(duration, 2)
                            })

                            # Mark next day's early checkout as processed
                            next_log['Times'] = next_log['Times'][1:]

                            # Process any remaining times in the next day
                            remaining_next_times = next_log['Times']
                            if len(remaining_next_times) >= 2:
                                next_pair_limit = len(remaining_next_times) if len(remaining_next_times) % 2 == 0 else len(remaining_next_times) - 1
                                for t in range(0, next_pair_limit, 2):
                                    try:
                                        start2 = datetime.combine(next_log['Date'], datetime.strptime(remaining_next_times[t], "%H:%M").time())
                                        end2 = datetime.combine(next_log['Date'], datetime.strptime(remaining_next_times[t + 1], "%H:%M").time())
                                        if end2 < start2:
                                            end2 += timedelta(days=1)
                                        duration2 = (end2 - start2).total_seconds() / 3600
                                        total_hours += duration2
                                        daily_details.append({
                                            "Date": next_log['Date'].strftime("%Y-%m-%d"),
                                            "Start": remaining_next_times[t],
                                            "End": remaining_next_times[t + 1],
                                            "Duration": round(duration2, 2)
                                        })
                                    except Exception as e:
                                        print(f"Pairing error on {next_log['Date']} for times {remaining_next_times[t]}-{remaining_next_times[t+1]}: {e}")
                            handled = True
                        else:
                            # Next day's first time is not early; report missing
                            missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover_time} checkout ???")
                            handled = True
                    else:
                        missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover_time} checkout ???")
                        handled = True
                else:
                    missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover_time} checkout ???")
                    handled = True

            elif len(unprocessed_times) > 1:
                # More than 1 unprocessed time left → flag them all
                for idx, leftover in unprocessed_times:
                    missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover} checkout ???")
                handled = True

            if not handled and len(unprocessed_times) == 0:
                # Everything was processed fine
                pass

            i += 1
          # Deduplicate daily_details by date, start, end combination
        seen = set()
        unique_details = []
        for d in daily_details:
            key = (d["Date"], d["Start"], d["End"])
            if key not in seen:
                seen.add(key)
                unique_details.append(d)
                  # Recalculate total_hours only from deduplicated details
        total_hours = sum(d["Duration"] for d in unique_details)
        result.append({
            "EmployeeName": name,
            "TotalHours": round(total_hours, 2),
            "MissingCheckouts": missing,
            "DailyDetails": unique_details

        })

    return result

# Streamlit UI
st.title("🕒 Attendance Analyzer from Excel")

# Add month selection
month = st.selectbox("Select Month", 
                    options=list(range(1, 13)),
                    index=6,  # Default to July (7)
                    format_func=lambda x: datetime(2025, x, 1).strftime('%B'))

uploaded_file = st.file_uploader("Upload Attendance Excel (.xls or .xlsx)", type=["xls", "xlsx"])

if uploaded_file:
    try:
        records = parse_excel(uploaded_file, month)
        summaries = analyze_attendance(records)
        summaries = filter_zero_hour_employees(summaries)

                  # --- Replace your current search box section with this: ---

        with st.container(border=True):
            st.markdown("### 🔎 Employee Search")
            search_name = st.text_input(
                label="Search by Employee Name",
                placeholder="Type a name to filter...",
                label_visibility="collapsed"  # Hide label for a cleaner look
            ).strip().lower()

        if search_name:
            # Use case-insensitive substring match with regex
            search_pattern = re.compile(re.escape(search_name), re.IGNORECASE)
            summaries = [
                summary for summary in summaries
                if search_pattern.search(summary["EmployeeName"])
            ]


        for summary in summaries:
            st.subheader(summary["EmployeeName"])
            st.write(f"**Total Hours Worked:** {summary['TotalHours']} hours")

            if summary.get("DailyDetails"):
                with st.expander("📅 Daily Breakdown"):
                    st.dataframe(pd.DataFrame(summary["DailyDetails"]))

            if summary.get("MissingCheckouts"):
                with st.expander("⚠️ Missing Checkouts"):
                    for miss in summary["MissingCheckouts"]:
                        st.markdown(f"- {miss}")

            st.markdown("---")

    except Exception as e:
        st.error(f"❌ Error parsing file: {e}")
        st.error("Please ensure the Excel file follows the expected format:")
        st.error("- Sheet name should be 'Attendance Logs'")
        st.error("- Name should be in column K (11th column)")
        st.error("- Days should be in the row below the name row")
        st.error("- Weekdays should be in the row below days")
        st.error("- Times should be in the row below weekdays")

