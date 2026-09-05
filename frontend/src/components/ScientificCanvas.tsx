import { useCallback, useEffect, useRef } from "react";
import {
  drainCurrent,
  gateSweeps,
  profileFields,
  profileValue,
  type ProfileField,
} from "../demo";

type DrawCanvas = (
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
) => void;

function useResponsiveCanvas(draw: DrawCanvas) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) {
      return;
    }

    const render = () => {
      const parentWidth = canvas.parentElement?.clientWidth ?? 0;
      const width = Math.max(320, Math.floor(parentWidth || canvas.clientWidth || 640));
      const fontScale = (parseFloat(getComputedStyle(document.documentElement).fontSize) || 18) / 18;
      const height = Math.max(240, Number(canvas.dataset.height ?? 360) * fontScale);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const context = canvas.getContext("2d");

      if (!context) {
        return;
      }

      canvas.width = Math.floor(width * ratio);
      canvas.height = Math.floor(height * ratio);
      canvas.style.height = `${height}px`;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      draw(context, width, height);
    };

    render();

    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(render);
    if (canvas.parentElement) {
      observer?.observe(canvas.parentElement);
    }
    window.addEventListener("resize", render);

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", render);
    };
  }, [draw]);

  return ref;
}

function drawGrid(
  context: CanvasRenderingContext2D,
  left: number,
  top: number,
  width: number,
  height: number,
  xDivisions: number,
  yDivisions: number,
) {
  context.save();
  context.strokeStyle = "rgba(92, 225, 212, 0.14)";
  context.lineWidth = 1;

  for (let index = 0; index <= xDivisions; index += 1) {
    const x = left + (width * index) / xDivisions;
    context.beginPath();
    context.moveTo(x, top);
    context.lineTo(x, top + height);
    context.stroke();
  }

  for (let index = 0; index <= yDivisions; index += 1) {
    const y = top + (height * index) / yDivisions;
    context.beginPath();
    context.moveTo(left, y);
    context.lineTo(left + width, y);
    context.stroke();
  }

  context.restore();
}

interface CanvasProps {
  ariaLabel: string;
}

interface ProfileCanvasProps extends CanvasProps {
  selectedField: ProfileField;
}

export function ProfileCanvas({ ariaLabel, selectedField }: ProfileCanvasProps) {
  const draw = useCallback<DrawCanvas>(
    (context, width, height) => {
      const tickSize = Math.max(14, Math.round((parseFloat(getComputedStyle(document.documentElement).fontSize) || 18) * 0.8));
      const axisSize = tickSize + 1;
      const margin = {
        left: tickSize * 4.8,
        right: 20,
        top: 26,
        bottom: axisSize * 3.4,
      };
      const plotWidth = width - margin.left - margin.right;
      const plotHeight = height - margin.top - margin.bottom;
      const minLog = 14;
      const maxLog = 21;
      const maxDepth = 0.8;
      const xDivisions = plotWidth < tickSize * 16 ? 2 : plotWidth < tickSize * 32 ? 4 : 8;

      context.fillStyle = "#041015";
      context.fillRect(0, 0, width, height);
      drawGrid(
        context,
        margin.left,
        margin.top,
        plotWidth,
        plotHeight,
        xDivisions,
        maxLog - minLog,
      );

      context.save();
      context.font = `${tickSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      context.fillStyle = "#9ab4bc";
      context.textAlign = "right";
      context.textBaseline = "middle";

      for (let exponent = minLog; exponent <= maxLog; exponent += 1) {
        const y =
          margin.top +
          plotHeight -
          ((exponent - minLog) / (maxLog - minLog)) * plotHeight;
        context.fillText(`10^${exponent}`, margin.left - 9, y);
      }

      context.textAlign = "center";
      context.textBaseline = "top";
      for (let index = 0; index <= xDivisions; index += 1) {
        const depth = (maxDepth * index) / xDivisions;
        const x = margin.left + (plotWidth * index) / xDivisions;
        context.fillText(depth.toFixed(1), x, margin.top + plotHeight + 10);
      }

      context.fillStyle = "#c2d4d8";
      context.font = `600 ${axisSize}px Inter, ui-sans-serif, system-ui`;
      context.fillText("Depth (μm)", margin.left + plotWidth / 2, height - 18);
      context.save();
      context.translate(15, margin.top + plotHeight / 2);
      context.rotate(-Math.PI / 2);
      context.fillText("Concentration (cm⁻³)", 0, 0);
      context.restore();

      context.fillStyle = "rgba(134, 207, 205, 0.08)";
      context.fillRect(margin.left, margin.top, plotWidth, 11);
      context.fillStyle = "rgba(138, 187, 196, 0.5)";
      context.font = `${Math.max(11, tickSize - 1)}px ui-monospace, SFMono-Regular, Menlo, monospace`;
      context.textAlign = "left";
      context.fillText("Si / surface", margin.left + 6, margin.top + 1);
      context.restore();

      for (const series of profileFields) {
        const active = series.id === selectedField;
        context.save();
        context.beginPath();

        for (let index = 0; index <= 160; index += 1) {
          const depth = (maxDepth * index) / 160;
          const value = profileValue(series.id, depth);
          const logValue = Math.min(maxLog, Math.max(minLog, Math.log10(value)));
          const x = margin.left + (depth / maxDepth) * plotWidth;
          const y =
            margin.top +
            plotHeight -
            ((logValue - minLog) / (maxLog - minLog)) * plotHeight;
          if (index === 0) {
            context.moveTo(x, y);
          } else {
            context.lineTo(x, y);
          }
        }

        context.strokeStyle = series.color;
        context.globalAlpha = active ? 1 : 0.24;
        context.lineWidth = active ? 2.6 : 1.1;
        context.shadowColor = active ? series.color : "transparent";
        context.shadowBlur = active ? 9 : 0;
        context.stroke();
        context.restore();
      }

      context.save();
      const markerX = margin.left + plotWidth * 0.525;
      context.strokeStyle = "rgba(232, 240, 242, 0.36)";
      context.setLineDash([4, 5]);
      context.beginPath();
      context.moveTo(markerX, margin.top);
      context.lineTo(markerX, margin.top + plotHeight);
      context.stroke();
      context.restore();
    },
    [selectedField],
  );

  const ref = useResponsiveCanvas(draw);

  return (
    <canvas
      ref={ref}
      className="science-canvas"
      data-height="350"
      role="img"
      aria-label={ariaLabel}
    />
  );
}


export function IvCanvas({ ariaLabel }: CanvasProps) {
  const draw = useCallback<DrawCanvas>((context, width, height) => {
    const tickSize = Math.max(14, Math.round((parseFloat(getComputedStyle(document.documentElement).fontSize) || 18) * 0.8));
    const axisSize = tickSize + 1;
    const margin = {
      left: tickSize * 4.8,
      right: 22,
      top: 26,
      bottom: axisSize * 3.4,
    };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const maxVoltage = 1.2;
    const maxCurrent = 0.32;
    const xDivisions = plotWidth < tickSize * 12 ? 2 : plotWidth < tickSize * 24 ? 3 : 6;
    const colors = ["#6f8190", "#55c8be", "#f2b75e", "#ff7086"];

    context.fillStyle = "#041015";
    context.fillRect(0, 0, width, height);
    drawGrid(context, margin.left, margin.top, plotWidth, plotHeight, xDivisions, 5);

    context.save();
    context.font = `${tickSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    context.fillStyle = "#9ab4bc";
    context.textAlign = "center";
    context.textBaseline = "top";
    for (let index = 0; index <= xDivisions; index += 1) {
      const voltage = (maxVoltage * index) / xDivisions;
      const x = margin.left + (plotWidth * index) / xDivisions;
      context.fillText(voltage.toFixed(1), x, margin.top + plotHeight + 10);
    }

    context.textAlign = "right";
    context.textBaseline = "middle";
    for (let index = 0; index <= 5; index += 1) {
      const current = (maxCurrent * index) / 5;
      const y = margin.top + plotHeight - (plotHeight * index) / 5;
      context.fillText(current.toFixed(2), margin.left - 9, y);
    }

    context.textAlign = "center";
    context.textBaseline = "alphabetic";
    context.fillStyle = "#c2d4d8";
    context.font = `600 ${axisSize}px Inter, ui-sans-serif, system-ui`;
    context.fillText("Vd (V)", margin.left + plotWidth / 2, height - 10);
    context.save();
    context.translate(15, margin.top + plotHeight / 2);
    context.rotate(-Math.PI / 2);
    context.fillText("Id (mA / μm)", 0, 0);
    context.restore();
    context.restore();

    gateSweeps.forEach((gateVoltage, curveIndex) => {
      context.save();
      context.beginPath();
      for (let index = 0; index <= 120; index += 1) {
        const drainVoltage = (maxVoltage * index) / 120;
        const current = drainCurrent(gateVoltage, drainVoltage);
        const x = margin.left + (drainVoltage / maxVoltage) * plotWidth;
        const y =
          margin.top +
          plotHeight -
          (Math.min(maxCurrent, current) / maxCurrent) * plotHeight;
        if (index === 0) {
          context.moveTo(x, y);
        } else {
          context.lineTo(x, y);
        }
      }
      context.strokeStyle = colors[curveIndex];
      context.lineWidth = curveIndex === gateSweeps.length - 1 ? 2.7 : 1.8;
      context.shadowColor = colors[curveIndex];
      context.shadowBlur = curveIndex === gateSweeps.length - 1 ? 8 : 0;
      context.stroke();
      context.restore();
    });
  }, []);

  const ref = useResponsiveCanvas(draw);

  return (
    <canvas
      ref={ref}
      className="science-canvas"
      data-height="390"
      role="img"
      aria-label={ariaLabel}
    />
  );
}
