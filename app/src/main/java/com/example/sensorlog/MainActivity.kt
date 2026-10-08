package com.example.sensorlog

import android.annotation.SuppressLint
import android.content.Intent
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.sensorlog.databinding.ActivityMainBinding
import java.util.ArrayDeque
import java.util.Locale
import kotlin.math.sqrt

/**
 * 多元感知融合 · 第 2 节课后任务②：实时加速度波形。
 * 第 3 项任务在保留波形的基础上，同步记录加速度计与陀螺仪的原始采样。
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var sm: SensorManager
    private lateinit var recorder: SensorSessionRecorder

    private var accelerometer: Sensor? = null
    private var gyroscope: Sensor? = null

    private val listener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> onAccelerometer(event)
                Sensor.TYPE_GYROSCOPE -> onGyroscope(event)
            }
        }

        override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {}
    }

    // UI 中的频率统计使用回调到达时间，文件中的质量统计使用 SensorEvent.timestamp。
    private val accelerometerEventTimes = ArrayDeque<Long>()
    private val gyroscopeEventTimes = ArrayDeque<Long>()
    private var accelerometerEvents = 0L
    private var gyroscopeEvents = 0L

    private var lastAccX = 0f
    private var lastAccY = 0f
    private var lastAccZ = 0f
    private var lastGyroX = 0f
    private var lastGyroY = 0f
    private var lastGyroZ = 0f

    private val uiHandler = Handler(Looper.getMainLooper())
    private val uiTick = object : Runnable {
        override fun run() {
            updateStats()
            uiHandler.postDelayed(this, 500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        recorder = SensorSessionRecorder(this)

        binding.helloWorldBtn.setOnClickListener {
            startActivity(Intent(this, HelloWorldActivity::class.java))
        }
        binding.startRecordingBtn.setOnClickListener { startRecording() }
        binding.stopRecordingBtn.setOnClickListener { stopRecording("用户手动停止") }

        ViewCompat.setOnApplyWindowInsetsListener(binding.main) { view, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
            insets
        }

        val sensors = (getSystemService(SENSOR_SERVICE) as SensorManager)
            .getSensorList(Sensor.TYPE_ALL)
        binding.sensorsTv.text = "设备传感器清单：\n" +
            sensors.joinToString("\n") { "· ${it.name}  [${it.vendor}]" }
        updateRecordingButtons()
    }

    private fun onAccelerometer(event: SensorEvent) {
        val (x, y, z) = event.values
        lastAccX = x
        lastAccY = y
        lastAccZ = z
        accelerometerEvents++
        accelerometerEventTimes.addLast(SystemClock.elapsedRealtime())
        recorder.write(event)
        binding.waveform.addSample(event.timestamp / 1_000_000L, floatArrayOf(x, y, z))
    }

    private fun onGyroscope(event: SensorEvent) {
        val (x, y, z) = event.values
        lastGyroX = x
        lastGyroY = y
        lastGyroZ = z
        gyroscopeEvents++
        gyroscopeEventTimes.addLast(SystemClock.elapsedRealtime())
        recorder.write(event)
    }

    @SuppressLint("SetTextI18n")
    private fun updateStats() {
        val now = SystemClock.elapsedRealtime()
        while (accelerometerEventTimes.isNotEmpty() && accelerometerEventTimes.first() < now - 3000L) {
            accelerometerEventTimes.removeFirst()
        }
        while (gyroscopeEventTimes.isNotEmpty() && gyroscopeEventTimes.first() < now - 3000L) {
            gyroscopeEventTimes.removeFirst()
        }

        val accelerometerHz = accelerometerEventTimes.size / 3.0
        val gyroscopeHz = gyroscopeEventTimes.size / 3.0
        binding.statusTv.text = String.format(
            Locale.US,
            "实测采样频率（3 s 窗）：加计 %.1f Hz｜陀螺 %.1f Hz\n累计回调：加计 %d｜陀螺 %d",
            accelerometerHz,
            gyroscopeHz,
            accelerometerEvents,
            gyroscopeEvents,
        )

        val accelerationMagnitude = sqrt(
            lastAccX * lastAccX + lastAccY * lastAccY + lastAccZ * lastAccZ
        )
        val gyroscopeMagnitude = sqrt(
            lastGyroX * lastGyroX + lastGyroY * lastGyroY + lastGyroZ * lastGyroZ
        )
        binding.valuesTv.text = String.format(
            Locale.US,
            "加速度（m/s²）：X=%.2f  Y=%.2f  Z=%.2f  |a|=%.2f\n" +
                "陀螺仪（rad/s）：X=%.3f  Y=%.3f  Z=%.3f  |ω|=%.3f",
            lastAccX,
            lastAccY,
            lastAccZ,
            accelerationMagnitude,
            lastGyroX,
            lastGyroY,
            lastGyroZ,
            gyroscopeMagnitude,
        )

        if (recorder.isRecording()) {
            val snapshot = recorder.snapshot()
            binding.recordingStatusTv.text = String.format(
                Locale.US,
                "正在采集：加计 %d 点｜陀螺 %d 点%s",
                snapshot.accelerometerCount,
                snapshot.gyroscopeCount,
                snapshot.error?.let { "\n写入异常：$it" }.orEmpty(),
            )
        }
    }

    private fun startRecording() {
        val accelerometer = accelerometer
        val gyroscope = gyroscope
        if (accelerometer == null || gyroscope == null) {
            binding.recordingStatusTv.text = "无法开始：本机缺少加速度计或陀螺仪。"
            updateRecordingButtons()
            return
        }

        try {
            val directory = recorder.start(accelerometer, gyroscope)
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            binding.recordingStatusTv.text = "采集已开始，页面将保持常亮。\n会话目录：${directory.absolutePath}"
        } catch (t: Throwable) {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            binding.recordingStatusTv.text = "采集启动失败：${t.message ?: t.javaClass.simpleName}"
        }
        updateRecordingButtons()
    }

    private fun stopRecording(reason: String) {
        val summary = recorder.stop(reason)
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (summary != null) {
            val accelerometerHz = String.format(Locale.US, "%.2f", summary.accelerometer.measuredHz)
            val gyroscopeHz = String.format(Locale.US, "%.2f", summary.gyroscope.measuredHz)
            binding.recordingStatusTv.text = buildString {
                append("采集完成：加计 ${summary.accelerometer.sampleCount} 点（$accelerometerHz Hz）")
                append("｜陀螺 ${summary.gyroscope.sampleCount} 点（$gyroscopeHz Hz）")
                append("\n目录：${summary.directory.absolutePath}")
                summary.error?.let { append("\n异常：$it") }
            }
        }
        updateRecordingButtons()
    }

    private fun updateRecordingButtons() {
        val recording = recorder.isRecording()
        val bothSensorsAvailable = accelerometer != null && gyroscope != null
        binding.startRecordingBtn.isEnabled = bothSensorsAvailable && !recording
        binding.stopRecordingBtn.isEnabled = recording
    }

    override fun onResume() {
        super.onResume()
        sm = getSystemService(SENSOR_SERVICE) as SensorManager
        accelerometer = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        gyroscope = sm.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

        accelerometer?.let {
            sm.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME, uiHandler)
        }
        gyroscope?.let {
            sm.registerListener(listener, it, SensorManager.SENSOR_DELAY_GAME, uiHandler)
        }

        binding.titleTv.text = "实时传感器 · 加计 + 陀螺"
        binding.sensorNamesTv.text = buildString {
            append("加速度计：${accelerometer?.name ?: "不可用"}")
            append("\n陀螺仪：${gyroscope?.name ?: "不可用"}")
        }
        updateRecordingButtons()
        uiHandler.removeCallbacks(uiTick)
        uiHandler.post(uiTick)
    }

    override fun onPause() {
        if (recorder.isRecording()) {
            stopRecording("Activity paused")
        }
        sm.unregisterListener(listener)
        uiHandler.removeCallbacks(uiTick)
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onPause()
    }
}