import logging
import numpy as np
import pandas as pd


def filter_points(points, min_interval):
    filtered = []
    last_idx = None
    for idx in points:
        if last_idx is None or idx - last_idx >= min_interval:
            filtered.append(idx)
            last_idx = idx
    return filtered


def filter_all_segments(df_after_pulse, min_interval=3):
    filtered_segments = []
    for segment_id, group_df in df_after_pulse.groupby('segment'):
        filtered_df = filter_after_pulses(group_df, min_interval)
        filtered_segments.append(filtered_df)
    # 合并所有过滤后的segment
    result_df = pd.concat(filtered_segments, ignore_index=True)
    return result_df

def cal_area(waveform_data, st: int, ed: int, baseline: int):
    sum_val = np.sum(waveform_data[st: ed])
    area = baseline * (ed - st) - sum_val
    pe_fact = (2./16384)*4.e-9/(50*1.6e-19)/1.e6  # 转换系数
    return area * pe_fact



def filter_after_pulses(df_after_pulse, min_interval=3):
    """
    过滤 after_pulse DataFrame 中 start 时间点间隔小于 min_interval 的行。
    如果两个 start 时间点间隔小于 min_interval，则滤除后一个时间点对应的行。
    
    参数:
        df_after_pulse: pandas.DataFrame，必须包含 'start' 列，且为数值类型。
        min_interval: int，最小间隔阈值，单位为样本数。
    
    返回:
        过滤后的 DataFrame。
    """
    # 先按 start 排序，确保顺序正确
    df_sorted = df_after_pulse.sort_values('min_point').reset_index(drop=True)
    
    # 用一个布尔列表标记哪些行保留，初始都保留
    keep = [True] * len(df_sorted)
    
    for i in range(1, len(df_sorted)):
        # 计算当前start与前一个start的差值
        diff = df_sorted.loc[i, 'min_point'] - df_sorted.loc[i-1, 'min_point']
        if diff < min_interval:
            # 间隔小于阈值，滤除当前行（i）
            keep[i] = False
    
    # 返回过滤后的 DataFrame
    return df_sorted[keep].reset_index(drop=True)

def filter_all_segments(df_after_pulse, min_interval=10):
    filtered_segments = []
    for segment_id, group_df in df_after_pulse.groupby('segment'):
        filtered_df = filter_after_pulses(group_df, min_interval)
        filtered_segments.append(filtered_df)
    # 合并所有过滤后的segment
    result_df = pd.concat(filtered_segments, ignore_index=True)
    return result_df
####----------------------------------------------------------------


def findpulse_st_ed(waveform_data: np.ndarray, baseline: int, referencePoint: int):
    """
    find the start, min, end index of pulse
    Args:
        waveform_data (np.ndarray): segment waveform data
        baseline (int): baseline of the segment
        referencePoint (int): reference point which over 20 adc in segment

    Returns:
        find the start, min, end index of referencePoint pulse, [-5, 15] window from referencePoint
    """
    
    start_range = max(0, referencePoint - 5)
    end_range = min(len(waveform_data), referencePoint + 5)

    min_index = referencePoint
    min_value = waveform_data[referencePoint]
    for i in range(start_range, end_range):
        if waveform_data[i] < min_value:
            min_value = waveform_data[i]
            min_index = i

    start_index = min_index
    while start_index > start_range:
        if (waveform_data[start_index] - waveform_data[start_index - 1]) < 0:
            start_index -= 1
        else:
            break

    end_index = min_index
    if end_index + 1 < end_range and waveform_data[min_index] == waveform_data[end_index + 1]:
        end_index += 1

    while end_index + 1 < end_range:
        if (waveform_data[end_index + 1] - waveform_data[end_index]) > 0:
            end_index += 1
        else:
            break

    return start_index, min_index, end_index



def afterpulse_scan_from_df(
    df_main: pd.DataFrame,    
    threshold: int = 20,
    afterpulse_min_interval: int = 35,
):
    """
    输入:
        df_main: 包含主脉冲信息的DataFrame，必须包含Ch, TTT, Baseline, st, ed, md, Hight, Area, Wave等列
        waveforms_dict: dict，key为TTT，value为对应波形np.ndarray
        threshold: 触发阈值
        main_pulse_height_threshold: 主脉冲高度阈值（用于判断主脉冲，后脉冲不判断）
        afterpulse_min_interval: 后脉冲起始点距离主脉冲结束点的最小间隔
    
    返回:
        pd.DataFrame，包含主脉冲和后脉冲信息
    """

    all_pulses = []

    for idx, row in df_main.iterrows():
        Ch = row['Ch']
        TTT = row['TTT']
        baseline = row['Baseline']
        st_main = row['st']
        ed_main = row['ed']
        minp_main = row['md']
        height_main = row['Hight']
        area_main = row['Area']
        waveform = row['Wave']

        # 先保存主脉冲信息
        main_pulse_info = {
            'Ch': Ch,
            'TTT': TTT,
            'segment': idx,
            'pulse_index': 0,
            'baseline': baseline,
            'start': st_main,
            'end': ed_main,
            'width': ed_main - st_main,
            'height': height_main,
            'min_point': minp_main,
            'area': area_main,
            'is_main_pulse': True,
            'time_interval_start': 0,
            'time_interval_min_point': 0,
        }
        all_pulses.append(main_pulse_info)

        # 获取对应波形
        # waveform = waveforms_dict.get(TTT, None)
        if waveform is None:
            print(f"Warning: TTT {TTT} waveform not found, skip afterpulse search")
            continue

        n = len(waveform)
        search_start = st_main + afterpulse_min_interval
        if search_start >= n:
            # 没有足够数据寻找后脉冲
            continue

        # 寻找后脉冲参考点：波形低于baseline - threshold的点
        ref_points = []
        above_threshold = False
        for i in range(search_start, n):
            if baseline - waveform[i] > threshold:
                if not above_threshold:
                    ref_points.append(i)
                    above_threshold = True
            else:
                above_threshold = False

        # 过滤相邻参考点，避免重复计数
        ref_points = filter_points(ref_points, 2)
        # ReferencePoints = filter_points(ReferencePoints, 2)

        pulse_idx_in_event = 1  # 后脉冲索引从1开始

        for ref_idx in ref_points:
            try:
                st, minp, ed = findpulse_st_ed(waveform, baseline, ref_idx)
            except Exception as e:
                # print(f"findpulse_st_ed error at TTT {TTT}, ref_idx {ref_idx}: {e}")
                continue

            if ed < st:
                continue

            pulse_height = baseline - waveform[minp]
            if pulse_height < threshold:
                continue

            area = cal_area(waveform, st, ed, baseline)

            time_interval_start = st - st_main
            time_interval_min_point = minp - minp_main

            after_pulse_info = {
                'Ch': Ch,                
                'TTT': TTT,
                'segment': idx,                
                'pulse_index': pulse_idx_in_event,
                'baseline': baseline,
                'start': st,
                'end': ed,
                'width': ed - st,
                'height': pulse_height,
                'min_point': minp,
                'area': area,
                'is_main_pulse': False,
                'time_interval_start': time_interval_start,
                'time_interval_min_point': time_interval_min_point,
            }
            all_pulses.append(after_pulse_info)
            pulse_idx_in_event += 1

    df_all = pd.DataFrame(all_pulses)
    return df_all
####-----------------------------------------
def cal_app_charge_ratio(df_after_pulse):
    """
    遍历所有 segment，计算每个 segment 的 after pulse 概率 (app)，
    返回一个列表，列表元素为字典，格式：{'segment': segment_id, 'app': app_value}
    """
    app_list = []
    segments = df_after_pulse['segment'].unique()
    total_main_pulses = []
    afterpulse_total = []
    for seg in segments:
        df_seg = df_after_pulse[df_after_pulse['segment'] == seg]
        after_pulses = df_seg.area[df_seg['pulse_index'] != 0].sum()
        main_pulses = df_seg.area[df_seg['pulse_index'] == 0].values.sum()
        afterpulse_total.append(after_pulses)
        total_main_pulses.append(main_pulses)
    app = sum(afterpulse_total) / sum(total_main_pulses)
    print(app)
    return app
