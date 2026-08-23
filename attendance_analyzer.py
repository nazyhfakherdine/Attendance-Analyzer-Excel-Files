import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
from collections import defaultdict

st.set_page_config(page_title="Attendance Analyzer", layout="wide")

# ==================== Dialog Modal (Pop-up Notification) ====================
@st.dialog("💰 Salary Calculation")
def show_salary_dialog(emp_name, total_hours, hourly_rate, salary):
    st.markdown(f"### 👤 Employee: **{emp_name}**")
    st.markdown("---")
    st.markdown(f"⏱️ **Total Hours:** `{total_hours} hrs`")
    st.markdown(f"💵 **Hourly Rate:** `${hourly_rate:,.2f} / hr`")
    st.markdown(f"### 🎯 **Total Salary:** `${salary:,.2f}`")
    st.markdown("---")
    if st.button("Close (X)", use_container_width=True):
        st.rerun()


# ==================== Excel Parsing ====================
def _find_sheet_with_columns(file, required_cols=("Name", "Time")):
    xls = pd.ExcelFile(file, engine="xlrd")
    for sheet in xls.sheet_names:
        df = xls.parse(sheet, nrows=5)
        cols = {str(c).strip().lower() for c in df.columns}
        if all(rc.lower() in cols for rc in required_cols):
            return sheet
    return xls.sheet_names[0]


def parse_excel(file, start_date=None, end_date=None):
    sheet = _find_sheet_with_columns(file)
    df = pd.read_excel(file, sheet_name=sheet, engine="xlrd")
    df.columns = [str(c).strip() for c in df.columns]

    col_map = {c.lower(): c for c in df.columns}
    if "name" not in col_map or "time" not in col_map:
        raise ValueError(
            f"Couldn't find 'Name' and 'Time' columns in sheet '{sheet}'. "
            f"Found columns: {list(df.columns)}"
        )
    name_col = col_map["name"]
    time_col = col_map["time"]

    df["_ParsedTime"] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=["_ParsedTime", name_col])
    df[name_col] = df[name_col].astype(str).str.strip()
    df = df[df[name_col] != ""]

    df["_Date"] = df["_ParsedTime"].dt.date

    if start_date and end_date:
        df = df[(df["_Date"] >= start_date) & (df["_Date"] <= end_date)]

    if df.empty:
        return []

    rows = []
    grouped = df.groupby([name_col, "_Date"])["_ParsedTime"]
    for (name, day), times in grouped:
        times_sorted = sorted(times.tolist())
        time_strs = [t.strftime("%H:%M") for t in times_sorted]
        rows.append({
            "EmployeeName": name,
            "Date": datetime(day.year, day.month, day.day),
            "Times": time_strs,
            "OriginalRawTime": ", ".join(time_strs)
        })

    rows.sort(key=lambda x: x["Date"])
    return rows


# ==================== Attendance Analysis ====================
def filter_zero_hour_employees(summaries):
    return [summary for summary in summaries if summary["TotalHours"] > 0]


def analyze_attendance(records):
    grouped = defaultdict(list)
    for r in records:
        grouped[r['EmployeeName']].append(r)

    result = []

    for name, logs in grouped.items():
        logs.sort(key=lambda x: x['Date'])
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

        day_totals = defaultdict(float)
        day_entries = defaultdict(list)

        for d in daily_details:
            day_totals[d["Date"]] += d["Duration"]
            day_entries[d["Date"]].append(d)

        unique_details = []
        for date_str in sorted(day_totals.keys()):
            total_day_hours = round(day_totals[date_str], 2)
            
            # معرفة اليوم هل هو سبت أو أحد (5 = السبت، 6 = الأحد)
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
            is_weekend = dt_obj.weekday() in [5, 6]

            if is_weekend:
                # إذا اشتغل 7 ساعات أو أكتر بالسبت أو الأحد
                if total_day_hours >= 7.0:
                    overtime = round(total_day_hours - 7.0, 2)
                    calculated_duration = round(9.0 + overtime, 2)
                else:
                    overtime = 0.0
                    calculated_duration = total_day_hours
            else:
                # الأيام العادية (باقي أيام الأسبوع)
                overtime = round(max(0.0, total_day_hours - 9.0), 2)
                calculated_duration = total_day_hours

            starts = [e["Start"] for e in day_entries[date_str]]
            ends = [e["End"] for e in day_entries[date_str]]

            unique_details.append({
                "Date": date_str,
                "Start": starts[0],
                "End": ends[-1],
                "Duration": calculated_duration,
                "Overtime": overtime
            })

        total_hours = sum(d["Duration"] for d in unique_details)
        total_overtime = sum(d["Overtime"] for d in unique_details)
        total_normal = total_hours - total_overtime

        result.append({
            "EmployeeName": name,
            "TotalHours": round(total_hours, 2),
            "TotalNormalHours": round(total_normal, 2),
            "TotalOvertime": round(total_overtime, 2),
            "MissingCheckouts": missing,
            "DailyDetails": unique_details
        })

    return result


# ==================== Main Streamlit UI ====================
st.title("🕒 Attendance Analyzer from Excel")

uploaded_file = st.file_uploader("Upload Attendance Excel (.xls or .xlsx)", type=["xls", "xlsx"])

if uploaded_file:
    try:
        all_records = parse_excel(uploaded_file)

        if not all_records:
            st.warning("No attendance records found in this file.")
        else:
            all_dates = [r["Date"].date() for r in all_records]
            min_date, max_date = min(all_dates), max(all_dates)

            st.markdown("### 📅 Date Range Filter")
            selected_range = st.date_input(
                "Filter attendance records by date range:",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date
            )

            if isinstance(selected_range, tuple) and len(selected_range) == 2:
                start_date, end_date = selected_range
            else:
                start_date, end_date = min_date, max_date

            records = parse_excel(uploaded_file, start_date=start_date, end_date=end_date)
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
                emp_name = summary['EmployeeName']
                st.subheader(f"👤 {emp_name}")

                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric(label="Total Hours", value=f"{summary['TotalHours']} hrs")
                m_col2.metric(label="Total Normal Hours", value=f"{summary['TotalNormalHours']} hrs")
                m_col3.metric(label="Total Overtime", value=f"{summary['TotalOvertime']} hrs")

                col1, col2 = st.columns([2, 1])
                with col1:
                    hourly_rate = st.number_input(
                        f"Hourly rate ($/hr) for {emp_name}",
                        min_value=0.0, value=1.0, step=0.5, key=f"rate_{emp_name}"
                    )
                with col2:
                    st.markdown(
                        "<div style='display:flex; justify-content:center; align-items:center; height:100%; padding-top:10px;'>",
                        unsafe_allow_html=True
                    )
                    apply_rate = st.button("Apply", key=f"apply_{emp_name}")
                    st.markdown("</div>", unsafe_allow_html=True)

                if apply_rate:
                    calculated_salary = round(summary['TotalHours'] * hourly_rate, 2)
                    show_salary_dialog(emp_name, summary['TotalHours'], hourly_rate, calculated_salary)

                if summary.get("DailyDetails"):
                    daily_df = pd.DataFrame(summary["DailyDetails"])
                    
                    daily_df["DayName"] = pd.to_datetime(daily_df["Date"]).dt.strftime("%a")
                    daily_df["Date"] = daily_df["Date"] + " (" + daily_df["DayName"] + ")"
                    daily_df.drop(columns=["DayName"], inplace=True)

                    columns_order = ["Date", "Start", "End", "Duration", "Overtime"]
                    daily_df = daily_df[columns_order]

                    with st.expander("📅 Daily Breakdown"):
                        st.dataframe(daily_df, use_container_width=True)

                if summary.get("MissingCheckouts"):
                    with st.expander("⚠️ Missing Checkouts"):
                        for miss in summary["MissingCheckouts"]:
                            st.markdown(f"- {miss}")

                st.markdown("---")

    except Exception as e:
        st.error(f"❌ Error parsing file: {e}")