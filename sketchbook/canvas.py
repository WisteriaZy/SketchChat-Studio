"""Pixel-coordinate region editor: wheel zoom, middle-button pan, corner resize."""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene

class RegionCanvas(QGraphicsView):
    regionChanged = Signal(list)
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.picture = self.scene().addPixmap(QPixmap())
        self.region = QRectF()
        self.editable = False
        self.mode = None
        self.image_size = (0, 0)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor('#e8edf3'))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(360, 300)
    def set_image(self, pixmap, reset=False):
        size = (pixmap.width(), pixmap.height())
        changed = size != self.image_size
        self.image_size = size
        self.picture.setPixmap(pixmap)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        if reset or changed:
            self.fit()
    def fit(self):
        if not self.picture.pixmap().isNull():
            self.fitInView(self.picture, Qt.AspectRatioMode.KeepAspectRatio)
    def set_region(self, region):
        x1, y1, x2, y2 = region
        self.region = QRectF(x1, y1, x2-x1, y2-y1)
        self.viewport().update()
    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.region.isEmpty():
            return
        pen = QPen(QColor('#2563eb' if self.editable else '#94a3b8'), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(37, 99, 235, 22))
        painter.drawRect(self.region)
        if self.editable:
            radius = 4 / max(self.transform().m11(), .01)
            painter.setBrush(QColor('white'))
            for point in (self.region.topLeft(), self.region.topRight(), self.region.bottomLeft(), self.region.bottomRight()):
                painter.drawRect(QRectF(point.x()-radius, point.y()-radius, radius*2, radius*2))
    def wheelEvent(self, event):
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if .03 <= self.transform().m11() * factor <= 15:
            self.scale(factor, factor)
        event.accept()
    def point(self, event):
        point = self.mapToScene(event.position().toPoint())
        point.setX(max(0, min(self.image_size[0], point.x())))
        point.setY(max(0, min(self.image_size[1], point.y())))
        return point
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.mode = 'pan'
            self.last_pan = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() != Qt.MouseButton.LeftButton or not self.editable:
            return super().mousePressEvent(event)
        self.origin = self.point(event)
        self.before = QRectF(self.region)
        self.mode = 'draw'
        radius = 10 / max(self.transform().m11(), .01)
        corners = [self.region.topLeft(), self.region.topRight(), self.region.bottomLeft(), self.region.bottomRight()]
        for index, corner in enumerate(corners):
            if (corner-self.origin).manhattanLength() < radius:
                self.mode = 'resize'
                self.anchor = corners[3-index]
                break
        else:
            if self.region.contains(self.origin):
                self.mode = 'move'
    def mouseMoveEvent(self, event):
        if self.mode == 'pan':
            delta = event.position() - self.last_pan
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value()-int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value()-int(delta.y()))
            self.last_pan = event.position()
        elif self.mode in ('draw', 'resize', 'move'):
            point = self.point(event)
            if self.mode == 'move':
                delta = point - self.origin
                x = max(0, min(self.image_size[0]-self.before.width(), self.before.x()+delta.x()))
                y = max(0, min(self.image_size[1]-self.before.height(), self.before.y()+delta.y()))
                self.region = QRectF(x, y, self.before.width(), self.before.height())
            else:
                self.region = QRectF(self.anchor if self.mode == 'resize' else self.origin, point).normalized()
            self.viewport().update()
        else:
            super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        if self.mode in ('draw', 'resize', 'move'):
            r = self.region
            values = [round(r.left()), round(r.top()), round(r.right()), round(r.bottom())]
            if values[2] > values[0] and values[3] > values[1]:
                self.regionChanged.emit(values)
            else:
                self.region = self.before
                self.viewport().update()
        self.mode = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)
