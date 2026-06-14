# EPD-nRF5 Battery Service 固件补丁说明

目标：让当前 `windows_epd_upload.py` 能读取墨水屏设备真实电量，并在上传 dashboard 前把电量覆盖到页眉。

## 结论

上游 `tsl0922/EPD-nRF5` 默认的电量显示只存在于固件原生日历/时钟 GUI 模式：

- `EPD/EPD_service.c` 的 `epd_gui_update()` 调用 `EPD_ReadVoltage()`。
- `GUI/GUI.c` 的 `DrawBattery()` 把电压/电池条画到固件自己生成的画面上。
- 整图上传模式走 `INIT -> WRITE_IMG -> REFRESH`，不会调用 `DrawBattery()`。
- 默认固件没有暴露标准 BLE Battery Service `0x180F` / Battery Level `0x2A19`。

因此，当前 dashboard 要显示真实电量，最小正确改法是：在 EPD-nRF5 固件里新增标准 Battery Service，把 `EPD_ReadVoltage()` 换算成百分比后写入 Battery Level characteristic。

## 当前 Windows 端已经支持的 UUID

`windows_epd_upload.py` 已经尝试读取：

```text
00002a19-0000-1000-8000-00805f9b34fb
```

也就是标准 Battery Level characteristic。固件只要实现这个特征，Windows 上传流程会自动：

1. 连接 EPD-nRF5。
2. 读取 Battery Level。
3. 将 `电量 NN%` 覆盖到图片页眉。
4. 再执行 `INIT -> WRITE_IMG -> REFRESH` 上传整图。

## 固件改动方案

以下改法适用于基于 Nordic SDK 的 EPD-nRF5 工程。具体函数名可能因 SDK 版本略有差异，但应放在 `EPD/EPD_service.c` / `EPD/EPD_service.h` 附近，复用现有 `ble_epd_t` 服务上下文。

### 1. 在 `EPD/EPD_service.h` 扩展状态

给 `ble_epd_t` 增加 Battery Service 与 Battery Level characteristic handle：

```c
typedef struct
{
    uint16_t service_handle;
    ble_gatts_char_handles_t char_handles;
    ble_gatts_char_handles_t app_ver_handles;

    // 新增：标准 BLE Battery Service 0x180F / Battery Level 0x2A19
    uint16_t battery_service_handle;
    ble_gatts_char_handles_t battery_level_handles;

    uint8_t uuid_type;
    uint16_t conn_handle;
    uint8_t model;
    uint8_t display_mode;
    bool busy;
} ble_epd_t;
```

如果上游结构体字段顺序不同，只需把两个新增字段加进去，不要删除原字段。

### 2. 在 `EPD/EPD_service.c` 加电压到百分比换算

上游 `GUI/GUI.c` 内部已有 `batt_cal()`，但它是 `static`，不能直接跨文件调用。为避免牵动 GUI 文件，建议在 `EPD_service.c` 里放一个小型换算函数：

```c
static uint8_t battery_percent_from_voltage(uint16_t voltage)
{
    // EPD_ReadVoltage() 返回估算 VDD 毫伏。
    // 这里使用保守线性映射：3.0V=0%, 4.2V=100%。
    // 如果你的设备是 2xAAA/纽扣电池，可按实际曲线调整阈值。
    if (voltage <= 3000) {
        return 0;
    }
    if (voltage >= 4200) {
        return 100;
    }
    return (uint8_t)(((uint32_t)(voltage - 3000) * 100u) / 1200u);
}
```

如果想和原生日历模式显示完全一致，可以把 `GUI/GUI.c` 的 `batt_cal()` 抽到公共头文件里复用；但最小补丁不建议扩大改动面。

### 3. 新增 Battery Service 初始化函数

在 `EPD/EPD_service.c` 中增加：

```c
static ret_code_t battery_service_init(ble_epd_t *p_epd)
{
    ret_code_t err_code;
    ble_uuid_t ble_uuid;
    ble_add_char_params_t add_char_params;
    uint8_t initial_level = battery_percent_from_voltage(EPD_ReadVoltage());

    ble_uuid.type = BLE_UUID_TYPE_BLE;
    ble_uuid.uuid = BLE_UUID_BATTERY_SERVICE;  // 0x180F

    err_code = sd_ble_gatts_service_add(
        BLE_GATTS_SRVC_TYPE_PRIMARY,
        &ble_uuid,
        &p_epd->battery_service_handle
    );
    VERIFY_SUCCESS(err_code);

    memset(&add_char_params, 0, sizeof(add_char_params));
    add_char_params.uuid              = BLE_UUID_BATTERY_LEVEL_CHAR; // 0x2A19
    add_char_params.uuid_type         = BLE_UUID_TYPE_BLE;
    add_char_params.init_len          = sizeof(initial_level);
    add_char_params.max_len           = sizeof(initial_level);
    add_char_params.p_init_value      = &initial_level;
    add_char_params.char_props.read   = 1;
    add_char_params.char_props.notify = 1;
    add_char_params.read_access       = SEC_OPEN;
    add_char_params.cccd_write_access = SEC_OPEN;

    return characteristic_add(
        p_epd->battery_service_handle,
        &add_char_params,
        &p_epd->battery_level_handles
    );
}
```

需要确认相关头文件已可见：

```c
#include "ble_srv_common.h"
#include "EPD_driver.h"
```

如果当前 `EPD_service.c` 已经包含这些头文件，则不要重复添加。

### 4. 在 `epd_service_init()` 中调用 Battery Service 初始化

上游 `epd_service_init()` 目前只创建自定义 EPD service、EPD data characteristic 和 app version characteristic。保留原逻辑，在成功创建 app version characteristic 后调用：

```c
err_code = characteristic_add(p_epd->service_handle, &add_char_params, &p_epd->app_ver_handles);
VERIFY_SUCCESS(err_code);

return battery_service_init(p_epd);
```

如果原函数最后是 `return characteristic_add(...)`，需要改成先保存 `err_code`，再 `VERIFY_SUCCESS(err_code)`，最后 `return battery_service_init(p_epd);`。

### 5. 刷新 Battery Level 值

建议在两个地方更新 characteristic：

1. 初始化时：`battery_service_init()` 已写入初始值。
2. 每次固件 timer 或 GUI 更新时：调用下面函数更新最新电量。

新增函数：

```c
static void battery_level_update(ble_epd_t *p_epd)
{
    uint8_t level = battery_percent_from_voltage(EPD_ReadVoltage());

    ble_gatts_value_t gatts_value;
    memset(&gatts_value, 0, sizeof(gatts_value));
    gatts_value.len     = sizeof(level);
    gatts_value.offset  = 0;
    gatts_value.p_value = &level;

    (void)sd_ble_gatts_value_set(
        p_epd->conn_handle,
        p_epd->battery_level_handles.value_handle,
        &gatts_value
    );
}
```

然后在 `ble_epd_on_timer(...)` 或 `epd_gui_update(...)` 开头/结尾调用：

```c
battery_level_update(p_epd);
```

如果担心 SAADC 读电压耗电，可只在连接后、上传前、或每分钟更新一次；当前 Windows 上传器默认 600 秒安全间隔，实时性要求不高。

## 编译注意

如果编译时报这些符号未定义：

- `BLE_UUID_BATTERY_SERVICE`
- `BLE_UUID_BATTERY_LEVEL_CHAR`

可在 `EPD_service.c` 顶部补充兼容定义：

```c
#ifndef BLE_UUID_BATTERY_SERVICE
#define BLE_UUID_BATTERY_SERVICE 0x180F
#endif

#ifndef BLE_UUID_BATTERY_LEVEL_CHAR
#define BLE_UUID_BATTERY_LEVEL_CHAR 0x2A19
#endif
```

如果 `ble_add_char_params_t` 不支持 `char_props.notify` 或 `cccd_write_access`，先只保留 `read`；Windows 当前只需要 read，不依赖 notify。

## Windows 端验证

刷入固件后，在 Windows 应用目录运行：

```powershell
cd D:\Green_soft\nrf_epd_bde7
.\.venv\Scripts\python.exe .\windows_epd_upload.py --probe-gatt --scan-timeout 25
```

然后手动安全上传一次。该命令不执行上传前清屏，直接用 `interleaved_count=0` 慢速可靠写入，避免 BLE 快写导致半屏或残影；显式 `--no-clear-refresh` 可以避免任何调试清屏触发可见白屏 full refresh 覆盖最终图像：

```powershell
.\.venv\Scripts\python.exe .\windows_epd_upload.py --interleaved-count 0 --no-clear-before-upload --clear-cycles 1 --no-clear-refresh --clear-wait-seconds 35 --refresh-wait-seconds 35 --ignore-runtime-config
```

成功日志应出现类似：

```text
battery level: 87%
upload complete; waiting for EPD refresh
```

如果仍显示：

```text
battery level unavailable: ...
```

说明固件还没有正确暴露 `0x2A19`，或者 Windows 当前连接到的不是刷了补丁的 EPD 设备。

## 风险

- 需要重新编译并刷写 EPD-nRF5 固件。
- 改 BLE GATT 表后，手机/Windows 可能缓存旧 GATT，必要时取消配对、重启蓝牙或换设备地址重新扫描。
- 电压到百分比映射依赖供电方式；锂电池、纽扣电池、AAA 电池曲线不同，阈值可能需要按实际调整。
- 默认上游日历模式显示的是电压/电池条，不一定是真实线性百分比；新增标准 Battery Level 要求 0-100 百分比，因此需要映射。
