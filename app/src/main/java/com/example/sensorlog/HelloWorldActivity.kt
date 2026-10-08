package com.example.sensorlog

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * 课件“二十行，请出传感器数据”的最小可运行版本。
 * 核心流程：Manager -> Sensor -> Listener -> registerListener(GAME) -> onPause 注销。
 */
class HelloWorldActivity : AppCompatActivity() {

    private lateinit var sm: SensorManager
    private var accelerometer: Sensor? = null
    private lateinit var valuesTv: TextView
    private lateinit var statusTv: TextView
    private var sampleCount = 0L

    private val listener = object : SensorEventListener {
        override fun onSensorChanged(e: SensorEvent) {
            val (x, y, z) = e.values // 机体坐标，m/s²
            sampleCount++
            valuesTv.text = String.format(
                java.util.Locale.US,
                "X = %+.3f\nY = %+.3f\nZ = %+.3f",
                x, y, z
            )
            statusTv.text = "Hello World · 回调已运行\n累计回调：$sampleCount\n时间戳：${e.timestamp} ns"
        }

        override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {}
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hello_world)
        valuesTv = findViewById(R.id.helloValuesTv)
        statusTv = findViewById(R.id.helloStatusTv)

        sm = getSystemService(SENSOR_SERVICE) as SensorManager
        accelerometer = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        findViewById<TextView>(R.id.helloSensorTv).text =
            accelerometer?.name ?: "本机无加速度计"
    }

    override fun onResume() {
        super.onResume()
        accelerometer?.let {
            sm.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME) // 档位
            statusTv.text = "Hello World · 等待传感器回调…"
        } ?: run {
            valuesTv.text = "X = --\nY = --\nZ = --"
            statusTv.text = "本机无加速度计"
        }
    }

    override fun onPause() {
        sm.unregisterListener(listener) // 记得注销
        super.onPause()
    }
}