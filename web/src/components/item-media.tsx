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
  if (gif) {
    return (
      <video
        ref={(el) => {
          if (el) el.muted = true
        }}
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        poster={poster}
        aria-label={item.alt || "Animated GIF"}
        className="bg-muted w-full cursor-pointer rounded-lg"
        onClick={(event) => {
          const video = event.currentTarget
          if (video.paused) void video.play()
          else video.pause()
        }}
      >
        <source src={playable} />
      </video>
    )
  }
  return (
    <video
      controls
      playsInline
      preload="metadata"
      poster={poster}
      className="bg-muted w-full rounded-lg"
    >
      <source src={playable} />
    </video>
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
