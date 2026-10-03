import { useRef, useState } from "react"
import { PauseIcon, PlayIcon } from "lucide-react"

import { ItemImage } from "@/components/item-image"
import {
  isAnimatedGif,
  isVimeoEmbed,
  isYoutubeEmbed,
  playableVideoUrl,
  siteHost,
  type ItemMedia,
} from "@/lib/links"
import { cn } from "@/lib/utils"

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00"
  const total = Math.floor(seconds)
  const minutes = Math.floor(total / 60)
  const remain = total % 60
  return `${minutes}:${remain.toString().padStart(2, "0")}`
}

function WebsiteCard({ item }: { item: ItemMedia }) {
  const href = item.url
  const image = item.image_url
  const site = item.site_name || siteHost(href)
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="hover:bg-muted/40 overflow-hidden rounded-lg border border-border"
    >
      {image && (
        <ItemImage
          src={image}
          alt=""
          className="bg-muted aspect-video w-full object-cover"
        />
      )}
      <span className="flex flex-col gap-1 p-3">
        <span className="text-muted-foreground truncate text-xs">{site}</span>
        {item.title && (
          <span className="text-sm leading-snug font-medium">{item.title}</span>
        )}
        {item.description && (
          <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
            {item.description}
          </span>
        )}
      </span>
    </a>
  )
}

function VideoPlayer({ item }: { item: ItemMedia }) {
  const src = item.url
  const poster = item.preview_url || item.image_url || undefined
  const embed = item.embed || isYoutubeEmbed(src) || isVimeoEmbed(src)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [paused, setPaused] = useState(true)
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  if (embed) {
    return (
      <div className="bg-muted relative aspect-video w-full overflow-hidden rounded-lg">
        <iframe
          src={src}
          title={item.title || item.alt || "Video"}
          className="absolute inset-0 size-full border-0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
    )
  }
  const gif = isAnimatedGif(item)
  const playable = playableVideoUrl(src)

  function toggle() {
    const video = videoRef.current
    if (!video) return
    if (video.paused) void video.play()
    else video.pause()
  }

  return (
    <div className="bg-muted overflow-hidden rounded-lg">
      <div className="relative">
        <video
          ref={(el) => {
            videoRef.current = el
            if (el && gif) el.muted = true
          }}
          src={playable}
          poster={poster}
          autoPlay={gif}
          loop={gif}
          muted={gif}
          playsInline
          preload="auto"
          aria-label={gif ? item.alt || "Animated GIF" : item.alt || "Video"}
          className="w-full"
          onPlay={() => setPaused(false)}
          onPause={() => setPaused(true)}
          onLoadedMetadata={(event) => {
            const next = event.currentTarget.duration
            setDuration(Number.isFinite(next) ? next : 0)
          }}
          onTimeUpdate={(event) => setProgress(event.currentTarget.currentTime)}
        />
        <button
          type="button"
          onClick={toggle}
          aria-label={paused ? (gif ? "Play GIF" : "Play video") : "Pause"}
          className="absolute inset-0 flex items-center justify-center"
        >
          {paused && (
            <span className="bg-background/80 text-foreground flex size-12 items-center justify-center rounded-full shadow-sm">
              <PlayIcon className="size-5 translate-x-px" />
            </span>
          )}
        </button>
      </div>
      {!gif && duration > 0 && (
        <div className="flex items-center gap-2 px-2 py-1.5">
          <button
            type="button"
            onClick={toggle}
            aria-label={paused ? "Play video" : "Pause video"}
            className="text-foreground flex size-7 shrink-0 items-center justify-center"
          >
            {paused ? <PlayIcon className="size-4" /> : <PauseIcon className="size-4" />}
          </button>
          <span className="text-muted-foreground w-9 shrink-0 text-xs tabular-nums">
            {formatTime(progress)}
          </span>
          <input
            type="range"
            min={0}
            max={duration}
            step={0.1}
            value={Math.min(progress, duration)}
            aria-label="Seek"
            onChange={(event) => {
              const next = Number(event.target.value)
              const video = videoRef.current
              if (video) video.currentTime = next
              setProgress(next)
            }}
            className="w-full"
          />
          <span className="text-muted-foreground w-9 shrink-0 text-right text-xs tabular-nums">
            {formatTime(duration)}
          </span>
        </div>
      )}
    </div>
  )
}

export function ItemMediaList({
  media,
  className,
}: {
  media: ItemMedia[]
  className?: string
}) {
  if (media.length === 0) return null
  return (
    <div className={cn("flex flex-col gap-3", className)}>
      {media.map((item, index) => {
        const key = `${item.kind}-${item.tco || item.url}-${index}`
        if (item.kind === "photo") {
          return (
            <ItemImage
              key={key}
              src={item.url}
              alt={item.alt || ""}
              className="bg-muted w-full rounded-lg object-cover"
            />
          )
        }
        if (item.kind === "video") {
          return <VideoPlayer key={key} item={item} />
        }
        return <WebsiteCard key={key} item={item} />
      })}
    </div>
  )
}
