package com.example.sensorlog

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * 真机端到端冒烟：直接驱动 SensorSessionRecorder，使用设备真实传感器采集，
 * 验证 accelerometer.csv / gyroscope.csv / labels.csv / metadata.json 的最终状态。
 *
 * 不使用 adb shell input，因此不受小米 HyperOS 的 INJECT_EVENTS 限制。
 */
@RunWith(AndroidJUnit4::class)
class SensorSessionRecorderDeviceTest {

    private data class DeviceFixture(
        val sensorManager: SensorManager,
        val accelerometer: Sensor,
        val gyroscope: Sensor,
    )

    private fun fixture(): DeviceFixture {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
        val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        assertNotNull("设备缺少加速度计", accelerometer)
        assertNotNull("设备缺少陀螺仪", gyroscope)
        return DeviceFixture(sensorManager, accelerometer!!, gyroscope!!)
    }

    private class WritingListener(private val recorder: SensorSessionRecorder) : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            recorder.write(event)
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    @Test
    fun recordsRealSensorDataWithLabelsAndMetadata() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val device = fixture()
        val recorder = SensorSessionRecorder(context)
        val config = SessionConfig(
            routeName = "instrumented-device-smoke",
            devicePlacement = "手持",
            orientation = "屏幕朝上平放",
            targetDurationSeconds = 5,
            note = "connectedAndroidTest 真机冒烟",
        )
        val directory = recorder.start(device.accelerometer, device.gyroscope, config)

        val listener = WritingListener(recorder)
        val handler = Handler(Looper.getMainLooper())
        device.sensorManager.registerListener(
            listener, device.accelerometer, SensorManager.SENSOR_DELAY_GAME, handler,
        )
        device.sensorManager.registerListener(
            listener, device.gyroscope, SensorManager.SENSOR_DELAY_GAME, handler,
        )

        try {
            Thread.sleep(2500)
            assertTrue("第 1 次打点应成功", recorder.markEvent("开始步行"))
            Thread.sleep(700)
            assertTrue("第 2 次打点应成功", recorder.markEvent("到达"))
            Thread.sleep(2800)
        } finally {
            device.sensorManager.unregisterListener(listener)
        }

        val summary = recorder.stop("connectedAndroidTest 完成")
        assertNotNull("停止后应返回 summary", summary)
        assertTrue("加速度计应采到真实样本", summary!!.accelerometer.sampleCount > 0)
        assertTrue("陀螺仪应采到真实样本", summary.gyroscope.sampleCount > 0)
        assertEquals("应有 2 次事件打点", 2L, summary.labelCount)

        assertTrue(
            "accelerometer.csv 应存在且非空",
            File(directory, "accelerometer.csv").let { it.exists() && it.length() > 0 },
        )
        assertTrue(
            "gyroscope.csv 应存在且非空",
            File(directory, "gyroscope.csv").let { it.exists() && it.length() > 0 },
        )

        val labelLines = File(directory, "labels.csv").readLines()
        assertEquals("timestamp_elapsed_ns,wall_time_epoch_ms,label", labelLines.first())
        assertEquals("labels.csv 应为表头 + 2 条事件", 3, labelLines.size)
        assertTrue(labelLines[1].endsWith(",开始步行"))
        assertTrue(labelLines[2].endsWith(",到达"))

        val metadata = JSONObject(File(directory, "metadata.json").readText())
        assertEquals(2, metadata.getInt("schema_version"))
        assertEquals("completed", metadata.getString("status"))
        assertEquals("instrumented-device-smoke", metadata.getString("route_name"))
        assertEquals("手持", metadata.getString("device_placement"))
        assertEquals("屏幕朝上平放", metadata.getString("orientation"))
        assertEquals(5, metadata.getInt("target_duration_seconds"))
        assertEquals(2, metadata.getJSONObject("labels").getInt("count"))
        assertTrue(metadata.getString("app_version").isNotBlank())
    }

    private fun acquireWakeLock(context: Context): PowerManager.WakeLock? {
        return try {
            val powerManager = context.getSystemService(Context.POWER_SERVICE) as PowerManager
            powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "SensorLogTest:twoMinuteSmoke",
            ).apply {
                setReferenceCounted(false)
                acquire(5 * 60 * 1000L)
            }
        } catch (t: Throwable) {
            null
        }
    }

    /** 对应任务清单第 6 步：用真机做约 2 分钟的带标签冒烟采集。 */
    @Test
    fun recordsTwoMinuteLabelledSmokeSession() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val device = fixture()
        val recorder = SensorSessionRecorder(context)
        val config = SessionConfig(
            routeName = "instrumented-2min-smoke",
            devicePlacement = "手持",
            orientation = "屏幕朝上平放",
            targetDurationSeconds = 120,
            note = "2 分钟带标签真机冒烟",
        )
        val directory = recorder.start(device.accelerometer, device.gyroscope, config)
        val wakeLock = acquireWakeLock(context)

        val listener = WritingListener(recorder)
        val handler = Handler(Looper.getMainLooper())
        device.sensorManager.registerListener(
            listener, device.accelerometer, SensorManager.SENSOR_DELAY_GAME, handler,
        )
        device.sensorManager.registerListener(
            listener, device.gyroscope, SensorManager.SENSOR_DELAY_GAME, handler,
        )

        val schedule = listOf(
            8L to "开始步行",
            45L to "上车",
            80L to "下车",
            110L to "到达",
        )
        var elapsed = 0L
        try {
            schedule.forEach { (atSecond, label) ->
                Thread.sleep((atSecond - elapsed) * 1000L)
                assertTrue("打点应成功：$label", recorder.markEvent(label))
                elapsed = atSecond
            }
            Thread.sleep((122L - elapsed) * 1000L)
        } finally {
            device.sensorManager.unregisterListener(listener)
            wakeLock?.let { if (it.isHeld) it.release() }
        }

        val summary = recorder.stop("2 分钟真机冒烟完成")
        assertNotNull(summary)
        assertTrue("2 分钟应采到足量加速度样本", summary!!.accelerometer.sampleCount > 5000)
        assertTrue("2 分钟应采到足量陀螺样本", summary.gyroscope.sampleCount > 2000)
        assertEquals("应有 4 次事件打点", 4L, summary.labelCount)

        val metadata = JSONObject(File(directory, "metadata.json").readText())
        assertEquals("completed", metadata.getString("status"))
        assertEquals("instrumented-2min-smoke", metadata.getString("route_name"))
        assertEquals(120, metadata.getInt("target_duration_seconds"))
        assertEquals(4, metadata.getJSONObject("labels").getInt("count"))

        val labels = File(directory, "labels.csv").readLines().drop(1)
        assertEquals(4, labels.size)
        listOf("开始步行", "上车", "下车", "到达").forEachIndexed { index, label ->
            assertTrue("第 ${index + 1} 条标签应为 $label", labels[index].endsWith(",$label"))
        }

        InstrumentationRegistry.getInstrumentation().sendStatus(
            0,
            Bundle().apply {
                putString("session_directory", directory.absolutePath)
                putLong("accelerometer_samples", summary.accelerometer.sampleCount)
                putLong("gyroscope_samples", summary.gyroscope.sampleCount)
                putLong("label_count", summary.labelCount)
            },
        )
    }
}
