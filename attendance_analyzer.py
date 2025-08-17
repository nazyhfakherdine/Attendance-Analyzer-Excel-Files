import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
from collections import defaultdict

st.set_page_config(page_title="Attendance Analyzer", layout="wide")

# ==================== Excel Parsing ====================
def parse_excel(file, month):
    workbook = pd.read_excel(file, sheet_name="Attendance Logs", header=None)
    rows = []

    for idx, row in workbook.iterrows():
        if str(row[9]).strip() == "Name":
            name = str(workbook.iloc[idx][11]).strip()
            nums = workbook.iloc[idx + 1]
            days = workbook.iloc[idx + 2]
            times = workbook.iloc[idx + 3]

            first_day_col = None
            for col in range(len(workbook.columns)):
                day_str = str(nums[col]).strip()
                if day_str.isdigit() and (1 <= int(day_str) <= 31):
                    first_day_col = col
                    break

            if first_day_col is None:
                raise ValueError("Couldn't find the starting day column in the sheet.")

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

    rows.sort(key=lambda x: x['Date'])
    return rows

# ==================== Attendance Analysis ====================
def filter_zero_hour_employees(summaries):
    return [summary for summary in summaries if summary["TotalHours"] > 0]

def calculate_daily_pay(weekday, hours_worked, hourly_rate):
    """
    حساب الأجر حسب اليوم:
    - السبت: 7 ساعات أساسية = أجر 9 ساعات أيام عادية
    - باقي الأيام: 9 ساعات أساسية
    - أي ساعة زيادة بعد الدوام تُحسب بنفس معدل الساعة
    """
    if weekday == 5:  # Saturday
        base_hours = 7
        base_pay = 9 * hourly_rate  # 7 ساعات = 9 ساعات أجر
    else:  # Mon-Fri
        base_hours = 9
        base_pay = base_hours * hourly_rate

    if hours_worked > base_hours:
        overtime_hours = hours_worked - base_hours
        overtime_pay = overtime_hours * hourly_rate
        total_pay = base_pay + overtime_pay
    else:
        total_pay = (hours_worked / base_hours) * base_pay

    return round(total_pay, 2)

def analyze_attendance(records):
    grouped = defaultdict(list)
    for r in records:
        grouped[r['EmployeeName']].append(r)

    result = []

    for name, logs in grouped.items():
        logs.sort(key=lambda x: x['Date'])
        total_hours = 0
        missing = []
        daily_details = []

        if logs:
            first_log = logs[0]
            first_times = first_log['Times']
            if first_times:
                first_time_obj = datetime.strptime(first_times[0], "%H:%M").time()
                if first_time_obj.hour < 4 or (first_time_obj.hour == 4 and first_time_obj.minute <= 30):
                    missing.append(
                        f"{first_log['Date'].strftime('%Y-%m-%d')} checkout at {first_times[0]} "
                        f"is likely for previous day not included in this file."
                    )
                    first_log['Times'] = first_log['Times'][1:]

        i = 0
        while i < len(logs):
            current = logs[i]
            times = current['Times']
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

                        processed_indices.update([t, t+1])
                    except Exception:
                        pass

            unprocessed_times = [(idx, times[idx]) for idx in range(len(times)) if idx not in processed_indices]

            if len(unprocessed_times) == 1:
                idx, leftover_time = unprocessed_times[0]
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
                            next_log['Times'] = next_log['Times'][1:]
                        else:
                            missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover_time} checkout ???")
                    else:
                        missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover_time} checkout ???")
                else:
                    missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover_time} checkout ???")

            elif len(unprocessed_times) > 1:
                for idx, leftover in unprocessed_times:
                    missing.append(f"{current['Date'].strftime('%Y-%m-%d')} check-in {leftover} checkout ???")

            i += 1

        seen = set()
        unique_details = []
        for d in daily_details:
            key = (d["Date"], d["Start"], d["End"])
            if key not in seen:
                seen.add(key)
                unique_details.append(d)

        total_hours = sum(d["Duration"] for d in unique_details)
        result.append({
            "EmployeeName": name,
            "TotalHours": round(total_hours, 2),
            "MissingCheckouts": missing,
            "DailyDetails": unique_details
        })

    return result

# ==================== Streamlit UI ====================
st.title("🕒 Attendance Analyzer from Excel")

month = st.selectbox(
    "Select Month",
    options=list(range(1, 13)),
    index=6,
    format_func=lambda x: datetime(2025, x, 1).strftime('%B')
)

uploaded_file = st.file_uploader("Upload Attendance Excel (.xls or .xlsx)", type=["xls", "xlsx"])

if uploaded_file:
    try:
        records = parse_excel(uploaded_file, month)
        summaries = analyze_attendance(records)
        summaries = filter_zero_hour_employees(summaries)

        with st.container():
            st.markdown("### 🔎 Employee Search")
            search_name = st.text_input(
                label="Search by Employee Name",
                placeholder="Type a name to filter...",
                label_visibility="collapsed"
            ).strip().lower()

        if search_name:
            search_pattern = re.compile(re.escape(search_name), re.IGNORECASE)
            summaries = [s for s in summaries if search_pattern.search(s["EmployeeName"])]

        for summary in summaries:
            st.subheader(summary["EmployeeName"])

            # --- Hourly rate input + Apply button ---
           # Hourly rate input + Apply button
            col1, col2 = st.columns([2, 1])
            with col1:
                hourly_rate = st.number_input(
                    f"Hourly rate for {summary['EmployeeName']}",
                    min_value=0.0, value=1.0, step=0.1, key=f"rate_{summary['EmployeeName']}"
                )
            with col2:
                st.markdown(
                    "<div style='display:flex; justify-content:center; align-items:center; height:100%; padding-top:10px;'>",
                    unsafe_allow_html=True
                )
                apply_rate = st.button("Apply", key=f"apply_{summary['EmployeeName']}")
                st.markdown("</div>", unsafe_allow_html=True)


            if summary.get("DailyDetails"):
                daily_df = pd.DataFrame(summary["DailyDetails"])
                # Add DayName column
                daily_df["DayName"] = pd.to_datetime(daily_df["Date"]).dt.strftime("%a")
                daily_df["Date"] = daily_df["Date"] + " (" + daily_df["DayName"] + ")"
                daily_df.drop(columns=["DayName"], inplace=True)

                # Calculate Pay only if Apply pressed
                if apply_rate:
                    pays = []
                    for i, row in daily_df.iterrows():
                        weekday = datetime.strptime(row["Date"][:10], "%Y-%m-%d").weekday()
                        pay = calculate_daily_pay(weekday, row["Duration"], hourly_rate)
                        pays.append(pay)
                    daily_df["Pay"] = pays
                    total_salary = sum(pays)
                else:
                    daily_df["Pay"] = ""
                    total_salary = 0

                with st.expander("📅 Daily Breakdown"):
                    st.dataframe(daily_df)
                    if apply_rate:
                        st.markdown(f"**Total Salary:** ${round(total_salary,2)}")

            if summary.get("MissingCheckouts"):
                with st.expander("⚠️ Missing Checkouts"):
                    for miss in summary["MissingCheckouts"]:
                        st.markdown(f"- {miss}")

            st.markdown("---")

    except Exception as e:
        st.error(f"❌ Error parsing file: {e}")
