name = input("What's your name? ")

if len(name.split()) < 2:
    name = input(f"'{name}'? Just the one name? How delightfully peasant-like. "
                 f"Kindly furnish us with your full name, if it isn't too much trouble: ")

print(f"Hi, {name}!")
