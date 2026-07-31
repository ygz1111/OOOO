import { useEffect, useRef } from 'react';

interface CyberMatrixCanvasProps {
  intensity?: number;
}

export function CyberMatrixCanvas({ intensity = 1 }: CyberMatrixCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
      initNodes();
    };

    window.addEventListener('resize', handleResize);

    const mouse = {
      x: width / 2,
      y: height / 2,
      radius: 180,
    };

    const handleMouseMove = (e: MouseEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    };

    window.addEventListener('mousemove', handleMouseMove);

    interface Node {
      x: number;
      y: number;
      vx: number;
      vy: number;
      radius: number;
      loadKw: number;
      type: 'substation' | 'transformer' | 'generator' | 'data';
      pulse: number;
      pulseSpeed: number;
    }

    interface ElectricPulse {
      fromIndex: number;
      toIndex: number;
      progress: number;
      speed: number;
      color: string;
    }

    let nodes: Node[] = [];
    let pulses: ElectricPulse[] = [];

    const initNodes = () => {
      nodes = [];
      pulses = [];
      const count = Math.floor((width * height) / 18000) * intensity;
      const nodeTypes: ('substation' | 'transformer' | 'generator' | 'data')[] = [
        'substation',
        'transformer',
        'generator',
        'data',
      ];

      for (let i = 0; i < count; i++) {
        nodes.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.4,
          vy: (Math.random() - 0.5) * 0.4,
          radius: Math.random() * 2.5 + 1.5,
          loadKw: Math.floor(Math.random() * 500 + 200),
          type: nodeTypes[Math.floor(Math.random() * nodeTypes.length)],
          pulse: Math.random() * Math.PI * 2,
          pulseSpeed: 0.02 + Math.random() * 0.03,
        });
      }

      for (let i = 0; i < Math.min(15, count); i++) {
        const from = Math.floor(Math.random() * nodes.length);
        let to = Math.floor(Math.random() * nodes.length);
        if (from !== to) {
          pulses.push({
            fromIndex: from,
            toIndex: to,
            progress: Math.random(),
            speed: 0.003 + Math.random() * 0.008,
            color: Math.random() > 0.5 ? '#06b6d4' : '#a855f7',
          });
        }
      }
    };

    initNodes();

    const render = () => {
      ctx.clearRect(0, 0, width, height);

      ctx.strokeStyle = 'rgba(6, 182, 212, 0.04)';
      ctx.lineWidth = 1;
      const gridSize = 60;
      for (let x = 0; x < width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      for (let y = 0; y < height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        n.x += n.vx;
        n.y += n.vy;
        n.pulse += n.pulseSpeed;

        if (n.x < 0 || n.x > width) n.vx *= -1;
        if (n.y < 0 || n.y > height) n.vy *= -1;

        const dx = mouse.x - n.x;
        const dy = mouse.y - n.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        for (let j = i + 1; j < nodes.length; j++) {
          const n2 = nodes[j];
          const ndx = n.x - n2.x;
          const ndy = n.y - n2.y;
          const nDist = Math.sqrt(ndx * ndx + ndy * ndy);

          if (nDist < 140) {
            const alpha = (1 - nDist / 140) * 0.25;
            ctx.strokeStyle = `rgba(6, 182, 212, ${alpha})`;
            ctx.lineWidth = 0.8;
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(n2.x, n2.y);
            ctx.stroke();
          }
        }

        const glowRadius = n.radius + Math.sin(n.pulse) * 1.5;
        const isHovered = dist < mouse.radius;

        ctx.beginPath();
        ctx.arc(n.x, n.y, Math.max(1, glowRadius), 0, Math.PI * 2);

        if (n.type === 'substation') {
          ctx.fillStyle = isHovered ? '#00f0ff' : 'rgba(6, 182, 212, 0.9)';
        } else if (n.type === 'generator') {
          ctx.fillStyle = isHovered ? '#f59e0b' : 'rgba(234, 179, 8, 0.9)';
        } else if (n.type === 'transformer') {
          ctx.fillStyle = isHovered ? '#c084fc' : 'rgba(168, 85, 247, 0.9)';
        } else {
          ctx.fillStyle = 'rgba(56, 189, 248, 0.8)';
        }
        ctx.fill();

        if (dist < mouse.radius) {
          const mouseAlpha = (1 - dist / mouse.radius) * 0.4;
          ctx.strokeStyle = `rgba(0, 240, 255, ${mouseAlpha})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(n.x, n.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.stroke();
        }
      }

      pulses.forEach((p) => {
        p.progress += p.speed;
        if (p.progress >= 1) {
          p.progress = 0;
          p.fromIndex = Math.floor(Math.random() * nodes.length);
          p.toIndex = Math.floor(Math.random() * nodes.length);
        }

        const n1 = nodes[p.fromIndex];
        const n2 = nodes[p.toIndex];
        if (n1 && n2) {
          const px = n1.x + (n2.x - n1.x) * p.progress;
          const py = n1.y + (n2.y - n1.y) * p.progress;

          ctx.beginPath();
          ctx.arc(px, py, 3, 0, Math.PI * 2);
          ctx.fillStyle = p.color;
          ctx.shadowBlur = 10;
          ctx.shadowColor = p.color;
          ctx.fill();
          ctx.shadowBlur = 0;
        }
      });

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('mousemove', handleMouseMove);
    };
  }, [intensity]);

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-0 opacity-85"
    />
  );
}
