---
name: create-plots
description: >
  Creates consistently high-quality, publication-ready plots.
  Use when the user asks to plot, chart, or visualize data, or requests
  figures for a report, paper, or presentation. Also use when asked to
  improve, clean up, or make an existing plot more aesthetically pleasing.
metadata:
  author: Guillaume Beardsell
  version: 0.1.0
---

# Create High Quality plots

## Instructions

Make plots suitable for a letter-size document with 1-inch margins. For all the text displayed on the figure (e.g., labels, axis text,  legends), the desired font is Open Sans and the font size should be 10 pt when the figure is rendered at its nominal size.

The axis limits should be chosen to minimize "empty space" on the plot, that is the axis should be trimmed in order for the data to be most visible. If the range for the axis (y or x) is greater than 5, then the axis limits should be chosen to be a integer. For instance, good axis limits would be from 0 to 20. Bad axis limits would be from -0.1 to 10.9.

If a legend is present, it should be checked that it does not obstruct any data. If it obstructs data, the legned should be moved somewhere else on the plot so that it does not obstruct data anymore. Options for placement include: top right, bottom right, top left, bottom left. If none of these options results in the legend not obstructing text, the axis limits shall be extended in order to create "empty space" on the plot and thus allowing the adequate placement of the legend.

When plotting physical quantities such as time, temperature, pressure, etc., the axis labels should include the unit in brackets, e.g., "Pressure [bar]".



