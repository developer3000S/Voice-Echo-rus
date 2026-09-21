    def _probe_local_model(self):
        """Animate a progress bar while checking the local Ollama model."""
        self._probe_step = 0
        self._probe_timer = QTimer(self)
        self._probe_timer.timeout.connect(self._probe_tick)
        self._probe_timer.start(250)
        self._probe_tick()

    def _probe_tick(self):
        bars = [
            "█░░░░░░░░░░░░░░",
            "████░░░░░░░░░░░",
            "████████░░░░░░░",
            "███████████░░░░",
            "███████████████",
        ]
        if self._probe_step < len(bars):
            self._s3_status.setText(bars[self._probe_step])
            if self._probe_step % 2 == 0:
                self._call_js("if(window.triggerPulse) window.triggerPulse();")
            self._probe_step += 1
        else:
            self._probe_timer.stop()

            model_name = self._defaults.get("local_ai_model", "minicpm5-2b")
            try:
                from llm_client import client as _llm
                ok = _llm._model_exists()
            except Exception:
                ok = False

            if ok:
                self._s3_status.setText("✓ Модель найдена")
                self._s3_status.setStyleSheet("color: #37ff5f; background: transparent; border: none;")
                self._s3_title.setText("✓ Локальная модель")
                self._s3_title.setStyleSheet("color: #37ff5f; background: transparent; border: none;")
                self._s3_sub.setText(f"{model_name}  ·  Готов")
                self._s3_sub.setStyleSheet("color: rgba(55,255,95,0.6); background: transparent; border: none;")
                self._s3_box.setStyleSheet("""
                    QFrame {
                        background: rgba(8, 10, 16, 220);
                        border: 1px solid rgba(55, 255, 95, 0.2);
                        border-radius: 20px;
                    }
                """)
            else:
                self._s3_status.setText("✕ Ollama не отвечает")
                self._s3_status.setStyleSheet("color: #ff3b30; background: transparent; border: none;")
                self._s3_sub.setText("Запустите Ollama и повторите настройку")
                self._s3_sub.setStyleSheet("color: rgba(255,59,48,0.6); background: transparent; border: none;")

