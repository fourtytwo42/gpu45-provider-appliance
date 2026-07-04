"""
Fixed text used for voice creation and model sample generation.
Same text for every voice so training data is consistent.
"""

# Paragraph used when creating a new voice (VoiceDesign). One clip per voice.
# Neutral, readable, about 3-5 sentences. Used as both generation text and training transcript.
VOICE_PARAGRAPH_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "Pack my box with five dozen liquor jugs. "
    "How vexingly quick daft zebras jump. "
    "Sphinx of black quartz, judge my vow. "
    "These sentences are used to generate a consistent sample for each voice."
)

# Single sentence used to generate a preview after training a CustomVoice model.
# Returned via GET /models/{id}/sample.
MODEL_SAMPLE_SENTENCE = (
    "This is a sample of the trained voice. You can use it to preview before choosing."
)
