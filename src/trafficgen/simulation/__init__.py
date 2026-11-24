"""Feeding the network flows into SUMO: flow and turn files, routes and a SUMO config.

This part reads only the output of the network flows and the ``[network]`` and ``[sumo]``
sections of the config. It does not use the junction counts.
"""
