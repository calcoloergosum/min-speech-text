from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import flask
import pydub
from pydub.audio_segment import AudioSegment
from sqlalchemy.engine import create_engine
from sqlalchemy.orm.decl_api import registry
from sqlalchemy.orm.session import sessionmaker
from sqlalchemy.schema import Column
from sqlalchemy.sql import sqltypes

app = flask.Flask("Minimalistic Speech Text Parallel Data Toolkit")

# DB setup
engine = create_engine(
    f"sqlite:///{(Path('.').parent / 'db.sql').as_posix()}",
    echo=True, future=True
)
MAPPER_REGISTRY = registry()
Base = MAPPER_REGISTRY.generate_base()


class Recording(Base):
    __tablename__ = 'recording'

    id = Column(sqltypes.Integer,
                primary_key=True,
                autoincrement=True,
                nullable=False)
    sample_rate = Column(sqltypes.Integer, nullable=False)
    bit_depth = Column(sqltypes.Integer, nullable=False)
    data = Column(sqltypes.LargeBinary, nullable=False)
    channels = Column(sqltypes.Integer, nullable=False)
    transcription = Column(sqltypes.String, nullable=False)

    def to_audiosegment(self) -> None:
        assert self.bit_depth % 8 == 0
        return AudioSegment(data=self.data,
                            frame_rate=self.sample_rate,
                            sample_width=self.bit_depth // 8,
                            channels=self.channels)

    @classmethod
    def from_audiosegment(cls, audio: AudioSegment,
        transcription: Optional[str] = None
    ) -> Recording:
        return cls(
            sample_rate=audio.frame_rate,
            bit_depth=audio.sample_width * 8,
            channels=audio.channels,
            data=audio.get_array_of_samples().tobytes(),
            transcription=transcription,
        )

MAPPER_REGISTRY.metadata.create_all(engine)
make_session = sessionmaker(engine)

# html
_app_html = (Path(__file__).parent / "app.html").open().read().replace("__TARGET_URL__", "/set")
app.route("/")(lambda: _app_html)

@app.route("/set", methods=["POST"])
def _set():
    filecontent = flask.request.files['audio_data'].read()
    format = flask.request.form['format']
    text = flask.request.form['text']

    if format not in ('webm', 'wav'):
        raise RuntimeError(f"Unknown Format {format}")

    s = io.BytesIO(filecontent)
    audio = pydub.AudioSegment.from_file(s, format=format)
    with make_session() as sess:
        recording = Recording.from_audiosegment(audio, transcription=text)
        sess.add(recording)
        sess.commit()
    return 'OK'


@app.route("/recordings")
def recordings_list():
    with make_session() as sess:
        id_text_pairs = sess.query(Recording).with_entities(Recording.id, Recording.transcription).all()
        contents = "<a href='/'>Register more recordings</a><br>"
        contents += (
            "<br>".join([
                f"<a href='/recordings/{id}/delete'>X</a> " +
                f"{id: >7}: <a href='/recordings/{id}'>'{text}'</a>"
                for id, text in id_text_pairs
            ])
            if id_text_pairs
            else "No recordings registered yet"
        )
        return f"<html><body>{contents}</body></html>"


@app.route("/recordings/<id>")
def _recordings(id):
    with make_session() as sess:
        with io.BytesIO() as buf:
            sess.query(Recording).get(id).to_audiosegment().export(buf)
            response = flask.make_response(buf.getvalue())
            buf.close()
            response.headers['Content-Type'] = 'audio/wav'
            response.headers['Content-Disposition'] = 'inline; filename=sound.wav'
            return response


@app.route("/recordings/<id>/delete")
def _recordings_delete(id):
    with make_session() as sess:
        record = sess.query(Recording).get(id)
        sess.delete(record)
        sess.commit()
        return 'OK'


@app.route("/null")
def null(): return "WTF!"


if __name__ == '__main__':
    app.run("0.0.0.0", 8080, debug=True)
