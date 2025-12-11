# app/audio_helper.py
import numpy as np
import soundfile as sf
import os
import uuid
import sounddevice as sd
import queue

# --- TUNING PARAMETERS ---
RMS_THRESHOLD = 0.05  # Lower for local mic (it's normalized -1.0 to 1.0)
SILENCE_DURATION = 1.0
RUDE_SILENCE_DURATION = 0.4
SAMPLE_RATE = 16000

class AudioBuffer:
    def __init__(self):
        self.buffer = []
        self.silence_start_time = 0
        self.is_recording = False
        self.q = queue.Queue() # Thread-safe queue for local mic

    def callback(self, indata, frames, time, status):
        """Callback for sounddevice (Local Mic)"""
        if status:
            print(f"Audio status: {status}")
        # Make a copy of the current chunk
        self.q.put(indata.copy())

    def get_chunk_from_queue(self):
        """Retrieve chunk from local mic queue if available."""
        if not self.q.empty():
            return self.q.get()
        return None

    def add_chunk(self, raw_data, is_local_mic=False):
        """
        Takes raw audio data, adds to buffer, returns loudness (RMS).
        """
        if is_local_mic:
            # Local mic (sounddevice) gives float32 [-1.0, 1.0]
            audio_data = raw_data.flatten()
            self.buffer.append(audio_data)
            # Calculate RMS
            rms = np.sqrt(np.mean(audio_data**2))
            return rms
        else:
            # Robot mic (WAMP) gives int16 [32767]
            audio_int16 = np.frombuffer(raw_data, dtype=np.int16)
            # Normalize to float32 for consistency in saving
            audio_float = audio_int16.astype(np.float32) / 32768.0
            self.buffer.append(audio_float)
            
            # RMS for int16 needs different threshold logic, 
            # but here we normalized it, so threshold 0.05 works for both.
            rms = np.sqrt(np.mean(audio_float**2))
            return rms

    def clear(self):
        self.buffer = []
        # Clear queue too if needed
        with self.q.mutex:
            self.q.queue.clear()

    def save_to_wav(self):
        """Saves current buffer to a temp WAV file for Whisper."""
        if not self.buffer:
            return None
        
        full_audio = np.concatenate(self.buffer)
        filename = f"temp_{uuid.uuid4().hex}.wav"
        
        sf.write(filename, full_audio, SAMPLE_RATE)
        return filename

    @staticmethod
    def cleanup(filename):
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except:
                pass