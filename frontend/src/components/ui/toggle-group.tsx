import * as React from "react"
import { Toggle as TogglePrimitive } from "@base-ui/react/toggle"
import { ToggleGroup as ToggleGroupPrimitive } from "@base-ui/react/toggle-group"
import { type VariantProps } from "class-variance-authority"
import { cn } from "cn"

import { toggleVariants } from "@/components/ui/toggle"

const ToggleGroupContext = React.createContext<VariantProps<typeof toggleVariants>>({
  size: "default",
  variant: "default",
})

function ToggleGroup({
  className,
  variant,
  size,
  children,
  ...props
}: ToggleGroupPrimitive.Props & VariantProps<typeof toggleVariants>) {
  return (
    <ToggleGroupPrimitive
      data-slot="toggle-group"
      className={cn("flex w-fit items-center rounded-md", className)}
      {...props}
    >
      <ToggleGroupContext.Provider value={{ variant, size }}>{children}</ToggleGroupContext.Provider>
    </ToggleGroupPrimitive>
  )
}

// Base UI's ToggleGroup lavora sempre su array di value (anche a scelta
// singola, a differenza di Radix che per type="single" usa una stringa) —
// questo wrapper espone una API single-value comoda per il caso comune
// (es. il selettore del range temporale del grafico dashboard), tenendo
// ToggleGroup "raw" disponibile per il caso multiple.
function ToggleGroupSingle({
  value,
  onValueChange,
  ...props
}: Omit<ToggleGroupPrimitive.Props, "value" | "defaultValue" | "onValueChange" | "multiple"> &
  VariantProps<typeof toggleVariants> & {
    value: string
    onValueChange: (value: string) => void
  }) {
  return (
    <ToggleGroup
      value={[value]}
      onValueChange={(values) => {
        if (values[0]) onValueChange(values[0])
      }}
      {...props}
    />
  )
}

function ToggleGroupItem({
  className,
  children,
  variant,
  size,
  ...props
}: TogglePrimitive.Props & VariantProps<typeof toggleVariants>) {
  const context = React.useContext(ToggleGroupContext)

  return (
    <TogglePrimitive
      data-slot="toggle-group-item"
      className={cn(
        toggleVariants({
          variant: context.variant || variant,
          size: context.size || size,
        }),
        "flex-auto shrink-0 rounded-none shadow-none first:rounded-l-md last:rounded-r-md focus:z-10 focus-visible:z-10",
        className
      )}
      {...props}
    >
      {children}
    </TogglePrimitive>
  )
}

export { ToggleGroup, ToggleGroupSingle, ToggleGroupItem }
