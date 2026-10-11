package com.example.sensorlog

import android.annotation.SuppressLint
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.view.WindowManager
import android.widget.AdapterView
import android.widget.ArrayAdapter
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.example.sensorlog.databinding.ActivityMainBinding
import java.util.ArrayDeque
import java.util.Locale
import kotlin.math.sqrt

/**
 * 多元感知融合 · 第 2 节课后任务：实时波形 + 双传感器原始采集。
 *
 * 采集前填写路线、手机位置、朝向和目标时长；采集中可以打事件标签，
 * 并实时显示已采集时长、样本数与是否达到目标时长。
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

        setupConfigInputs()
        setupEventInputs()

        binding.startRecordingBtn.setOnClickListener { startRecording() }
        binding.stopRecordingBtn.setOnClickListener { stopRecording(getString(R.string.stop_reason_manual)) }
        binding.markEventBtn.setOnClickListener { markEvent() }

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

    private fun setupConfigInputs() {
        binding.targetDurationEt.setText(SessionConfig.DEFAULT_TARGET_DURATION_SECONDS.toString())
        binding.placementSpinner.adapter = spinnerAdapter(R.array.device_placement_options)
        binding.orientationSpinner.adapter = spinnerAdapter(R.array.orientation_options)
    }

    private fun setupEventInputs() {
        binding.eventPresetSpinner.adapter = spinnerAdapter(R.array.event_preset_options)
        binding.eventPresetSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(
                parent: AdapterView<*>?,
                view: View?,
                position: Int,
                id: Long,
            ) {
                val preset = parent?.getItemAtPosition(position)?.toString().orEmpty()
                if (preset.isNotEmpty() && preset != getString(R.string.event_preset_custom)) {
                    binding.eventLabelEt.setText(preset)
                }
            }

            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
    }

    private fun spinnerAdapter(arrayRes: Int): ArrayAdapter<CharSequence> {
        return ArrayAdapter.createFromResource(this, arrayRes, android.R.layout.simple_spinner_item)
            .apply { setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
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
            val elapsed = formatDuration(snapshot.elapsedSeconds)
            val target = formatDuration(snapshot.targetDurationSeconds.toDouble())
            val progress = if (snapshot.targetReached) "已达到目标时长" else "未达到目标时长"
            binding.recordingStatusTv.text = buildString {
                append("正在采集：已采集 $elapsed / 目标 $target（$progress）")
                append("\n加速度计 ${snapshot.accelerometerCount} 点｜陀螺仪 ${snapshot.gyroscopeCount} 点")
                append("｜事件打点 ${snapshot.labelCount} 次")
                snapshot.error?.let { append("\n写入异常：$it") }
            }
        }
    }

    private fun markEvent() {
        if (!recorder.isRecording()) {
            binding.recordingStatusTv.text = "尚未开始采集，无法打点。"
            return
        }
        val custom = binding.eventLabelEt.text.toString().trim()
        val preset = binding.eventPresetSpinner.selectedItem?.toString().orEmpty()
        val label = custom.ifEmpty {
            if (preset == getString(R.string.event_preset_custom)) "" else preset
        }
        if (label.isEmpty()) {
            binding.recordingStatusTv.text = "请输入事件标签，或从下拉列表中选择一个预设标签。"
            return
        }

        val ok = recorder.markEvent(label)
        val snapshot = recorder.snapshot()
        binding.recordingStatusTv.text = if (ok) {
            "已打点：$label（累计 ${snapshot.labelCount} 次）"
        } else {
            "打点失败：当前没有进行中的采集会话。"
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

        val routeName = binding.routeNameEt.text.toString().trim()
        if (routeName.isEmpty()) {
            binding.recordingStatusTv.text = "无法开始：请先填写路线名称。"
            return
        }
        val placement = binding.placementSpinner.selectedItem?.toString().orEmpty()
        val orientation = binding.orientationSpinner.selectedItem?.toString().orEmpty()
        val targetDurationSeconds = binding.targetDurationEt.text.toString().toIntOrNull()
            ?.coerceAtLeast(1)
            ?: SessionConfig.DEFAULT_TARGET_DURATION_SECONDS

        val sessionConfig = SessionConfig(
            routeName = routeName,
            devicePlacement = placement,
            orientation = orientation,
            targetDurationSeconds = targetDurationSeconds,
            note = binding.noteEt.text.toString().trim(),
        )

        try {
            val directory = recorder.start(accelerometer, gyroscope, sessionConfig)
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            binding.recordingStatusTv.text =
                "采集已开始，页面将保持常亮。\n会话目录：${directory.absolutePath}"
            binding.collectFormContainer.visibility = View.GONE
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
                append("｜事件打点 ${summary.labelCount} 次")
                append("\n目录：${summary.directory.absolutePath}")
                summary.error?.let { append("\n异常：$it") }
            }
        }
        binding.collectFormContainer.visibility = View.VISIBLE
        updateRecordingButtons()
    }

    private fun updateRecordingButtons() {
        val recording = recorder.isRecording()
        val bothSensorsAvailable = accelerometer != null && gyroscope != null
        binding.startRecordingBtn.isEnabled = bothSensorsAvailable && !recording
        binding.stopRecordingBtn.isEnabled = recording
        binding.markEventBtn.isEnabled = recording
    }

    private fun formatDuration(totalSeconds: Double): String {
        val whole = totalSeconds.toLong().coerceAtLeast(0L)
        val minutes = whole / 60
        val seconds = whole % 60
        return String.format(Locale.US, "%02d:%02d", minutes, seconds)
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

        binding.titleTv.text = getString(R.string.main_title)
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
            stopRecording(getString(R.string.stop_reason_paused))
        }
        sm.unregisterListener(listener)
        uiHandler.removeCallbacks(uiTick)
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        super.onPause()
    }
}
