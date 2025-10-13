import gradio as gr
import os
import glob
import sqlite3
import cv2
import datetime
from videotofaces import video_to_faces

DB_FILE = "faces_db.sqlite"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fps REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            frame_number INTEGER,
            timestamp_seconds REAL,
            face_image_path TEXT,
            person_name TEXT,
            cluster_id INTEGER,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        )
    ''')
    conn.commit()
    conn.close()

def process_video(video_path, style):
    output_dir = "faces_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()

    video_to_faces(input_path=video_path, style=style, out_dir=output_dir)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    upload_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO videos (filename, filepath, upload_date, fps) VALUES (?, ?, ?, ?)",
                   (os.path.basename(video_path), os.path.abspath(video_path), upload_date, fps))
    video_id = cursor.lastrowid

    face_images = glob.glob(os.path.join(output_dir, "**/*.jpg"), recursive=True)
    for image_path in face_images:
        face_image_path = os.path.abspath(image_path)
        try:
            cluster_id = int(os.path.basename(os.path.dirname(image_path)))
        except ValueError:
            cluster_id = -1 # Or some other default for non-clustered faces

        filename_parts = os.path.basename(image_path).split('.')[0].split('_')
        frame_number = int(filename_parts[0])
        timestamp_seconds = frame_number / fps if fps > 0 else 0

        cursor.execute("INSERT INTO faces (video_id, frame_number, timestamp_seconds, face_image_path, cluster_id) VALUES (?, ?, ?, ?, ?)",
                       (video_id, frame_number, timestamp_seconds, face_image_path, cluster_id))

    conn.commit()
    conn.close()

    return face_images

init_db()

with gr.Blocks() as demo:
    gr.Markdown("# Video to Faces")
    with gr.Row():
        with gr.Column():
            video_input = gr.Video(label="Upload Video")
            style_input = gr.Radio(["live", "anime"], label="Style", value="live")
            submit_button = gr.Button("Submit")
        with gr.Column():
            gallery_output = gr.Gallery(label="Extracted Faces")

    submit_button.click(
        fn=process_video,
        inputs=[video_input, style_input],
        outputs=gallery_output
    )

if __name__ == "__main__":
    demo.launch(share=True)