"use client"

import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const spinnerVariants = cva(
  "animate-spin",
  {
    variants: {
      size: {
        sm: "size-4 stroke-6",
        default: "size-5 stroke-6",
        lg: "size-6 stroke-6",
        xl: "size-8 stroke-8",
      },
      variant: {
        default: "stroke-secondary-foreground",
        destructive: "stroke-destructive",
        outline: "stroke-border",
        secondary: "stroke-secondary-foreground",
        ghost: "stroke-muted-foreground",
        link: "stroke-primary",
        green: "stroke-green-600",
        blue: "stroke-blue-600",
        red: "stroke-red-600",
        gray: "stroke-gray-600",
      },
    },
    defaultVariants: {
      size: "default",
      variant: "default",
    },
  }
)

interface SpinnerProps extends VariantProps<typeof spinnerVariants> {
  className?: string
}

export default function Spinner({ 
  size,
  variant,
  className
}: SpinnerProps) {
  return (
    <div className={cn("relative", className)}>
      <svg 
        className={cn(spinnerVariants({ size, variant, className }))}
        viewBox="25 25 50 50"
      >
        <circle
          className="animate-dash"
          cx="50"
          cy="50"
          r="20"
          fill="none"
          strokeMiterlimit="10"
          strokeLinecap="round"
          strokeDasharray="1, 200"
          strokeDashoffset="0"
        />
      </svg>
      
      <style>{`
        @keyframes dash {
          0% {
            stroke-dasharray: 1, 200;
            stroke-dashoffset: 0;
          }
          50% {
            stroke-dasharray: 89, 200;
            stroke-dashoffset: -35px;
          }
          100% {
            stroke-dasharray: 89, 200;
            stroke-dashoffset: -124px;
          }
        }
        
        .animate-dash {
          animation: dash 2s ease-in-out infinite;
        }
      `}</style>
    </div>
  )
}