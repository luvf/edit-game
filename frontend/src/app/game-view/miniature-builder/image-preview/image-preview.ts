import {
  Component,
  computed,
  ElementRef,
  EventEmitter,
  inject,
  Input,
  OnChanges,
  OnInit,
  Output,
  signal,
  SimpleChanges,
  ViewChild
} from '@angular/core';
import {CommonModule} from '@angular/common';
import {TmpImageService} from '../../../features/tmp-images/tmp-image';
import {TmpImage} from '../../../features/tmp-images/tmp-image.model';

@Component({
  selector: 'app-images-preview',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './image-preview.html',
  styleUrl: './image-preview.css'
})
export class ImagesPreviewComponent implements OnInit, OnChanges {
  @Input() miniatureUrl: string | null = null;
  @Input() baseImageUrl: string | null = null;

  // Valeurs pilotées par le parent (FormGroup 'viewport')
  @Input() xOffset = 0;
  @Input() yOffset = 0;
  @Input() zoom = 1;

  // Remontée des changements vers le parent
  @Output() xOffsetChange = new EventEmitter<number>();
  @Output() yOffsetChange = new EventEmitter<number>();
  @Output() zoomChange = new EventEmitter<number>();


  @ViewChild('baseCanvas', {static: false}) baseCanvas?: ElementRef<HTMLCanvasElement>;
  miniatureImage = signal<TmpImage | null>(null);
  baseImage = signal<TmpImage | null>(null);
  miniatureImageUrl = computed(() => this.miniatureImage()?.image + '?timeStamp=$' + Date.now());
  readonly imageWidth = 1920
  readonly imageHeight = 1080
  readonly overlayWidth = 600
  private tmpImageService = inject(TmpImageService);
  private isDragging = false;
  private dragOffsetX = 0;
  private dragOffsetY = 0;


  /**
   * On init, fetch miniature and base images independently when URLs are provided.
   */
  ngOnInit() {

    // Load each image independently if the URL is present
    if (this.miniatureUrl) {
      this.tmpImageService.get(this.miniatureUrl).subscribe({
        next: (image) => this.miniatureImage.set(image),
        error: () => this.miniatureImage.set(null),
      });
    }

    if (this.baseImageUrl) {
      this.tmpImageService.get(this.baseImageUrl).subscribe({
        next: (image) => {
          this.baseImage.set(image);
          queueMicrotask(() => this.drawCanvas()); // Try a render after receipt
        },
        error: () => this.baseImage.set(null),
      });
    }
  }

  /**
   * Redraws the canvas when parameters or URLs change and ensures
   * the selection rectangle remains within bounds.
   */
  ngOnChanges(changes: SimpleChanges): void {
    if ('miniatureUrl' in changes) {
      if (this.miniatureUrl) {
        this.tmpImageService.get(this.miniatureUrl).subscribe({
          next: (image) => {
            this.miniatureImage.set(image);
            queueMicrotask(() => this.drawCanvas());
          },
          error: () => this.miniatureImage.set(null),
        });
      } else {
        this.miniatureImage.set(null);
      }
    }
    if ('baseImageUrl' in changes) {
      if (this.baseImageUrl) {
        this.tmpImageService.get(this.baseImageUrl).subscribe({
          next: (image) => {
            this.baseImage.set(image);
            queueMicrotask(() => this.drawCanvas());
          },
          error: () => this.baseImage.set(null),
        });
      } else {
        this.baseImage.set(null);
      }
    }
    if ('xOffset' in changes || 'yOffset' in changes || 'zoom' in changes) {
      const canvas = this.baseCanvas?.nativeElement;
      if (canvas) this.ensureRectInBounds(canvas.width, canvas.height);
      this.drawCanvas();
    }

  }

  /**
   * Starts dragging the selection rectangle when the mouse is pressed inside it.
   */
  onCanvasMouseDown(ev: MouseEvent) {
    const ctxInfo = this.getCanvasCtx();
    if (!ctxInfo) return;
    const {canvas} = ctxInfo;
    const pos = this.coordsFromEvent(ev);
    if (!pos) return;

    const r = this.getRectangle(canvas.width, canvas.height);
    if (this.rectContains(pos.x, pos.y, r)) {
      this.isDragging = true;
      this.dragOffsetX = pos.x - r.x;
      this.dragOffsetY = pos.y - r.y;
      (ev.currentTarget as HTMLCanvasElement).style.cursor = 'grabbing';
    }
  }

  /**
   * Updates the rectangle position while dragging and adjusts cursor feedback.
   */
  onCanvasMouseMove(ev: MouseEvent) {
    const ctxInfo = this.getCanvasCtx();
    const pos = this.coordsFromEvent(ev);
    if (!ctxInfo || !pos) return;
    const {canvas} = ctxInfo;

    if (this.isDragging) {
      // New top-left = mouse - offset (then clamp)
      const targetX = pos.x - this.dragOffsetX;
      const targetY = pos.y - this.dragOffsetY;
      this.setFromRectTopLeft(canvas.width, canvas.height, targetX, targetY);
      this.drawCanvas();
    } else {
      const r = this.getRectangle(canvas.width, canvas.height);
      const over = this.rectContains(pos.x, pos.y, r);
      (ev.currentTarget as HTMLCanvasElement).style.cursor = over ? 'grab' : 'default';

    }
  }

  /**
   * Ends dragging and resets the cursor.
   */
  onCanvasMouseUp() {
    this.isDragging = false;
    const canvas = this.baseCanvas?.nativeElement;
    if (canvas) canvas.style.cursor = 'default';
  }

  /**
   * Handles mouse wheel zooming centered around the cursor position.
   */
  onCanvasWheel(ev: WheelEvent) {
    ev.preventDefault();
    const ctxInfo = this.getCanvasCtx();
    const pos = this.coordsFromEvent(ev as unknown as MouseEvent);
    if (!ctxInfo || !pos) return;
    const {canvas} = ctxInfo;

    const r = this.getRectangle(canvas.width, canvas.height);
    const ax = r.w !== 0 ? (pos.x - r.x) / r.w : 0.5;
    const ay = r.h !== 0 ? (pos.y - r.y) / r.h : 0.5;

    const factor = ev.deltaY < 0 ? 0.9 : 1.1;
    const newZoom = Math.min(5, Math.max(1, this.zoom * factor));
    const oldZoom = this.zoom;
    if (newZoom === oldZoom) return;

    this.setZoom(newZoom);

    const w2 = (this.imageWidth - this.overlayWidth) / this.zoom;
    const h2 = this.imageHeight / this.zoom;

    const newX = pos.x - ax * w2;
    const newY = pos.y - ay * h2;

    this.setFromRectTopLeft(canvas.width, canvas.height, newX, newY);
    this.drawCanvas();
  }


  /**
   * Returns the 2D drawing context for the base canvas if available.
   *
   * @returns The canvas element and its 2D context, or null if not ready.
   */
  private getCanvasCtx(): { canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D } | null {
    const canvasEl = this.baseCanvas?.nativeElement;
    if (!canvasEl) return null;
    const ctx = canvasEl.getContext('2d');
    if (!ctx) return null;
    return {canvas: canvasEl, ctx};
  }

  /**
   * Computes the selection rectangle in canvas coordinates, based on current
   * normalized offsets and zoom. The rectangle represents the cropping area.
   *
   * @param cw - Canvas width (in pixels).
   * @param ch - Canvas height (in pixels).
   * @returns The rectangle: x, y (top-left), w, h (size), and z (zoom).
   */
  private getRectangle(cw: number, ch: number) {
    const z = this.zoom || 1;
    const rectX = this.xOffset * (cw - (cw - this.overlayWidth) / z);
    const rectY = this.yOffset * (ch - ch / z);
    const rectW = (this.imageWidth - this.overlayWidth) / z;
    const rectH = this.imageHeight / z;
    return {x: rectX, y: rectY, w: rectW, h: rectH, z};
  }


  /**
   * Translates a mouse event into canvas-space coordinates (accounting for CSS scaling).
   *
   * @param ev - Mouse event from the canvas.
   * @returns The point {x, y} in canvas pixels, or null if the canvas is not available.
   */
  private coordsFromEvent(ev: MouseEvent): { x: number, y: number } | null {
    const canvasEl = this.baseCanvas?.nativeElement;
    if (!canvasEl) return null;
    const rect = canvasEl.getBoundingClientRect();
    const scaleX = canvasEl.width / rect.width;
    const scaleY = canvasEl.height / rect.height;
    const x = (ev.clientX - rect.left) * scaleX;
    const y = (ev.clientY - rect.top) * scaleY;
    return {x, y};
  }

  /**
   * Checks whether a point lies inside a rectangle.
   *
   * @param mx - X coordinate of the point.
   * @param my - Y coordinate of the point.
   * @param r - Rectangle with x, y, w, h.
   * @returns True if the point is inside the rectangle, false otherwise.
   */
  private rectContains(mx: number, my: number, r: { x: number, y: number, w: number, h: number }): boolean {
    return mx >= r.x && mx <= r.x + r.w && my >= r.y && my <= r.y + r.h;
  }

  /**
   * Updates normalized offsets (xOffset, yOffset) from a desired top-left rectangle
   * position in canvas space. Applies clamping to keep the rectangle inside bounds
   * and emits x/y offset changes.
   *
   * @param cw - Canvas width (in pixels).
   * @param ch - Canvas height (in pixels).
   * @param rectX - Desired rectangle top-left X (in pixels).
   * @param rectY - Desired rectangle top-left Y (in pixels).
   */
  private setFromRectTopLeft(cw: number, ch: number, rectX: number, rectY: number) {
    const z = this.zoom || 1;
    const rectW = (this.imageWidth - this.overlayWidth) / z;
    const rectH = this.imageHeight / z;

    const clampedX = Math.min(Math.max(rectX, 0), Math.max(0, cw - rectW));
    const clampedY = Math.min(Math.max(rectY, 0), Math.max(0, ch - rectH));

    const denomX = (cw - (cw - this.overlayWidth) / z);
    const denomY = (ch - ch / z);
    const newXOffset = denomX !== 0 ? (clampedX) / denomX : 0;
    const newYOffset = denomY !== 0 ? (clampedY) / denomY : 0;

    const x = Math.min(1, Math.max(0, newXOffset));
    const y = Math.min(1, Math.max(0, newYOffset));
    this.xOffset = x;
    this.yOffset = y;

    // Émet aux parents (FormGroup 'viewport' sera mis à jour)
    this.xOffsetChange.emit(x);
    this.yOffsetChange.emit(y);
  }

  /**
   * Ensures the selection rectangle stays fully within the canvas.
   * If it overflows, adjusts offsets accordingly.
   *
   * @param cw - Canvas width (in pixels).
   * @param ch - Canvas height (in pixels).
   */
  private ensureRectInBounds(cw: number, ch: number) {
    const rectangle = this.getRectangle(cw, ch);
    let newX = rectangle.x;
    let newY = rectangle.y;

    if (rectangle.x < 0) newX = 0;
    if (rectangle.y < 0) newY = 0;
    if (rectangle.x + rectangle.w > cw) newX = Math.max(0, cw - rectangle.w);
    if (rectangle.y + rectangle.h > ch) newY = Math.max(0, ch - rectangle.h);

    if (newX !== rectangle.x || newY !== rectangle.y) {
      this.setFromRectTopLeft(cw, ch, newX, newY);
    }
  }

  /**
   * Sets a new zoom level, clamped to [1..5], emits the change, and
   * attempts to keep the rectangle within the canvas bounds.
   *
   * @param newZoom - Desired zoom factor.
   */
  private setZoom(newZoom: number) {
    const clamped = Math.min(5, Math.max(1, newZoom));
    if (clamped === this.zoom) return;
    this.zoom = clamped;

    const canvas = this.baseCanvas?.nativeElement;
    if (canvas) this.ensureRectInBounds(canvas.width, canvas.height);

    // Notifie le parent
    this.zoomChange.emit(this.zoom);
  }

  /**
   * Renders the base image into the canvas and overlays the selection rectangle
   * along with optional corner handles.
   *
   * The canvas size is synchronized to the image's natural size to preserve pixel accuracy.
   * If the base image is not available yet, the method is a no-op.
   */
  private drawCanvas(): void {
    const ctxInfo = this.getCanvasCtx();
    const base = this.baseImage();
    if (!ctxInfo || !base?.image) return;

    const {canvas, ctx} = ctxInfo;

    const img = new Image();
    img.src = base.image;
    img.onload = () => {
      // resize canvas to image size
      canvas.width = img.naturalWidth || img.width;
      canvas.height = img.naturalHeight || img.height;

      this.ensureRectInBounds(canvas.width, canvas.height);

      // draw background image
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

      // draw rect with white plain line
      const r = this.getRectangle(canvas.width, canvas.height);
      ctx.save();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 4;
      ctx.setLineDash([]); // plein
      ctx.strokeRect(r.x, r.y, r.w, r.h);

      // handles
      const handleSize = 8;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(r.x - handleSize / 2, r.y - handleSize / 2, handleSize, handleSize);
      ctx.fillRect(r.x + r.w - handleSize / 2, r.y - handleSize / 2, handleSize, handleSize);
      ctx.fillRect(r.x - handleSize / 2, r.y + r.h - handleSize / 2, handleSize, handleSize);
      ctx.fillRect(r.x + r.w - handleSize / 2, r.y + r.h - handleSize / 2, handleSize, handleSize);
      ctx.restore();
    };
    if (img.complete) {
      img.onload?.(null as any);
    }
  }


}
