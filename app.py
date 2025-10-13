
import gradio as gr
import os
import glob
from videotofaces import video_to_faces

def process_video(video_path, style):
    output_dir = "faces_output"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    video_to_faces(input_path=video_path, style=style, out_dir=output_dir)

    face_images = glob.glob(os.path.join(output_dir, "**/*.jpg"), recursive=True)
    return face_images

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
