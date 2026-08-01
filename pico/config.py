"""
Pico 2 smart farm hardware pin settings.

현재 단계에서는 PE350 Modbus RTU 읽기 테스트만 수행한다.
펌프/릴레이 출력 핀은 실제 단독 시험 전까지 이 파일에 정의하지 않는다.
"""

# RS485 / PmodRS485 Rev.B / PE350
UART_ID = 0
RS485_BAUD_RATE = 9600
RS485_BITS = 8
RS485_PARITY = None
RS485_STOP = 1

UART_TX_PIN = 0
UART_RX_PIN = 1
RS485_DE_PIN = 2
RS485_RE_PIN = 3

# I2C1 shared bus: SCD40 and AHT10
I2C_ID = 1
I2C_SDA_PIN = 14
I2C_SCL_PIN = 15
SCD40_I2C_ADDRESS = 0x62
AHT10_I2C_ADDRESS = 0x38

# DC relay control signals (GPIO number, not Pico physical pin number)
# Relay module input specifications and active HIGH/LOW are not defined yet.
RELAY_S1_LED_PIN = 16          # Pico physical pin 21
RELAY_S2_RAW_WATER_PIN = 17    # Pico physical pin 22
RELAY_S3_SUPPLY_PUMP_PIN = 18  # Pico physical pin 24
RELAY_S4_MIXING_PUMP_PIN = 19  # Pico physical pin 25
RELAY_S5_EC_PUMP_PIN = 20      # Pico physical pin 26
RELAY_S6_PH_PUMP_PIN = 21      # Pico physical pin 27
RELAY_S7_FAN_PIN = 22          # Pico physical pin 29

# PE350 / PE300 compatible Modbus RTU settings
PE350_SLAVE_ID = 31
PE350_EC_REGISTER = 0x0001
PE350_PH_REGISTER = 0x0002
PE350_TEMPERATURE_REGISTER = 0x0003

PE350_RESPONSE_TIMEOUT_MS = 1000
PE350_FRAME_SILENCE_MS = 20
