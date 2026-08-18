#include "statusled.h"

#include <sys/types.h>
#include <sys/stat.h>
#include "driver/gpio.h"

#include "ClassLogFile.h"
#include "../../include/defines.h"

// define `gpio_pad_select_gpip` for newer versions of IDF
#if (ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(4, 3, 0))
#include "esp_rom_gpio.h"
#define gpio_pad_select_gpio esp_rom_gpio_pad_select_gpio
#endif

static const char* TAG = "STATUSLED";

TaskHandle_t xHandle_task_StatusLED = NULL;
struct StatusLEDData StatusLEDData = {};


/* Not every board provides an internal status LED (see BOARD_HAS_STATUS_LED in defines.h).
   If there is none, the blink sequences are still processed, they just do not drive a GPIO. */
#ifdef BOARD_HAS_STATUS_LED
static void statusLedInit(void)
{
	gpio_pad_select_gpio(BLINK_GPIO); // Init the GPIO
	gpio_set_direction(BLINK_GPIO, GPIO_MODE_OUTPUT); // Set the GPIO as a push/pull output
}

static void statusLedSet(uint32_t level)
{
	gpio_set_level(BLINK_GPIO, level);
}
#else
static void statusLedInit(void) {}
static void statusLedSet(uint32_t) {}
#endif


void task_StatusLED(void *pvParameter)
{
    //ESP_LOGD(TAG, "task_StatusLED - create");
	while (StatusLEDData.bProcessingRequest) 
	{
		//ESP_LOGD(TAG, "task_StatusLED - start");
		struct StatusLEDData StatusLEDDataInt = StatusLEDData;

		statusLedInit();
		statusLedSet(1);// LED off

		for (int i=0; i<2; ) // Default: repeat 2 times
		{
			if (!StatusLEDDataInt.bInfinite)
				++i;

			for (int j = 0; j < StatusLEDDataInt.iSourceBlinkCnt; ++j)
			{
				statusLedSet(0);
				vTaskDelay(StatusLEDDataInt.iBlinkTime / portTICK_PERIOD_MS);
				statusLedSet(1);      
				vTaskDelay(StatusLEDDataInt.iBlinkTime / portTICK_PERIOD_MS);
			}

			vTaskDelay(500 / portTICK_PERIOD_MS);	// Delay between module code and error code

			for (int j = 0; j < StatusLEDDataInt.iCodeBlinkCnt; ++j)
			{
				statusLedSet(0);      
				vTaskDelay(StatusLEDDataInt.iBlinkTime / portTICK_PERIOD_MS);
				statusLedSet(1);
				vTaskDelay(StatusLEDDataInt.iBlinkTime / portTICK_PERIOD_MS);
			}
			vTaskDelay(1500 / portTICK_PERIOD_MS);	// Delay to signal new round
		}

		StatusLEDData.bProcessingRequest = false;
		//ESP_LOGD(TAG, "task_StatusLED - done/wait");
		vTaskDelay(10000 / portTICK_PERIOD_MS);	// Wait for an upcoming request otherwise continue and delete task to save memory
	}
	//ESP_LOGD(TAG, "task_StatusLED - delete");
	xHandle_task_StatusLED = NULL;
    vTaskDelete(NULL); // Delete this task due to no request
}


void StatusLED(StatusLedSource _eSource, int _iCode, bool _bInfinite)
{
	//ESP_LOGD(TAG, "StatusLED - start");

    if (_eSource == WLAN_CONN) {
		StatusLEDData.iSourceBlinkCnt = WLAN_CONN;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
	else if (_eSource == WLAN_INIT) {
		StatusLEDData.iSourceBlinkCnt = WLAN_INIT;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
	else if (_eSource == SDCARD_INIT) {
		StatusLEDData.iSourceBlinkCnt = SDCARD_INIT;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
	else if (_eSource == SDCARD_CHECK) {
		StatusLEDData.iSourceBlinkCnt = SDCARD_CHECK;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
    else if (_eSource == CAM_INIT) {
		StatusLEDData.iSourceBlinkCnt = CAM_INIT;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
    else if (_eSource == PSRAM_INIT) {
		StatusLEDData.iSourceBlinkCnt = PSRAM_INIT;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
	else if (_eSource == TIME_CHECK) {
		StatusLEDData.iSourceBlinkCnt = TIME_CHECK;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 250;
		StatusLEDData.bInfinite = _bInfinite;
	}
	else if (_eSource == AP_OR_OTA) {
		StatusLEDData.iSourceBlinkCnt = AP_OR_OTA;
		StatusLEDData.iCodeBlinkCnt = _iCode;
		StatusLEDData.iBlinkTime = 350;
		StatusLEDData.bInfinite = _bInfinite;
	}

	if (xHandle_task_StatusLED && !StatusLEDData.bProcessingRequest) {
		StatusLEDData.bProcessingRequest = true;
		BaseType_t xReturned = xTaskAbortDelay(xHandle_task_StatusLED);	// Reuse still running status LED task
		/*if (xReturned == pdPASS)
			ESP_LOGD(TAG, "task_StatusLED - abort waiting delay");*/
	}
	else if (xHandle_task_StatusLED == NULL) {
		StatusLEDData.bProcessingRequest = true;
		BaseType_t xReturned = xTaskCreate(&task_StatusLED, "task_StatusLED", 1280, NULL, tskIDLE_PRIORITY+1, &xHandle_task_StatusLED);
		if(xReturned != pdPASS)
		{
			xHandle_task_StatusLED = NULL;
			LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "task_StatusLED failed to create");
        	LogFile.WriteHeapInfo("task_StatusLED failed");
		}
	}
	else {
		ESP_LOGD(TAG, "task_StatusLED still processing, request skipped");	// Requests with high frequency could be skipped, but LED is only helpful for static states 
	}
	//ESP_LOGD(TAG, "StatusLED - done");
}


void StatusLEDOff(void)
{
	if (xHandle_task_StatusLED)
		vTaskDelete(xHandle_task_StatusLED); // Delete task for StatusLED to force stop of blinking
	
	statusLedInit();
	statusLedSet(1);// LED off
}